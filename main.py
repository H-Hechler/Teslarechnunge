"""Supercharger-Rechnungen über die offizielle Tesla Fleet API herunterladen."""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config.json'
REDIRECT = 'http://localhost:8585/callback'
TOKEN_URL = 'https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token'
BASES = {'EU': 'https://fleet-api.prd.eu.vn.cloud.tesla.com',
         'NA': 'https://fleet-api.prd.na.vn.cloud.tesla.com'}


class AppError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Bearer-Token niemals an einen anderen Host senden.


def request(url, token=None, form=None):
    headers = {'User-Agent': 'ChargingInvoiceDownloader/1.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = Request(url, data=data, headers=headers)
    for attempt in range(4):
        try:
            with build_opener(NoRedirect()).open(req, timeout=60) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                delay = exc.headers.get('Retry-After', '')
                time.sleep(min(int(delay), 60) if delay.isdigit() else 2 ** attempt)
                continue
            hints = {401: 'Erneut mit --login anmelden.',
                     403: 'Berechtigungen und regionale App-Registrierung im Tesla-Portal prüfen.',
                     402: 'Abrechnung im Tesla-Entwicklerportal prüfen.',
                     429: 'Anfragelimit erreicht. Später erneut versuchen.'}
            if exc.code == 400 and url == TOKEN_URL:
                import re

                body = exc.read().decode("utf-8", errors="replace")
                try:
                    details = json.loads(body)
                    error = details.get("error", "unknown")
                    description = details.get("error_description", "")
                    if not isinstance(error, str):
                        error = "unknown"
                    if not isinstance(description, str):
                        description = ""
                    message = re.sub(r"[^a-zA-Z0-9_. -]", "", f"{error}: {description}")[:200]
                except ValueError:
                    message = "Keine auswertbare OAuth-Fehlermeldung"

                raise AppError(f"Tesla OAuth HTTP 400: {message}") from None
        except (URLError, TimeoutError):
            raise AppError('Tesla nicht erreichbar. Internetverbindung prüfen.') from None


def token_request(form):
    return json.loads(request(TOKEN_URL, form=form))


class Vault:
    def __init__(self, client):
        try:
            import keyring
        except ImportError:
            raise AppError('Abhängigkeit fehlt: pip install -r requirements.txt') from None
        self.keyring = keyring
        self.client = client
        self.service = 'SuperchargerRechnungen:' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]

    def read(self):
        value = self.keyring.get_password(self.service, self.client)
        return json.loads(value) if value else {}

    def write(self, value):
        self.keyring.set_password(self.service, self.client, json.dumps(value))


def setup():
    print('Einmalige Einrichtung; Anleitung: README.md')
    client = input('Tesla Developer Client-ID: ').strip()
    secret = getpass.getpass('Tesla Developer Client-Secret (verdeckt): ').strip()
    region = input('Region EU oder NA [EU]: ').strip().upper() or 'EU'
    if not client or not secret or region not in BASES:
        raise AppError('Client-ID/Secret fehlen oder Region ungültig.')
    Vault(client).write({'client_secret': secret})
    CONFIG.write_text(json.dumps({'client_id': client, 'region': region}, indent=2), encoding='utf-8')


class Tesla:
    def __init__(self, config):
        self.client = config['client_id']
        self.base = BASES[config['region']]
        self.vault = Vault(self.client)
        self.credentials = self.vault.read()

    def save_tokens(self, result):
        if not result.get('access_token') or not result.get('refresh_token'):
            raise AppError('Tesla hat keine vollständigen Zugangstoken geliefert.')
        self.credentials.update(result)
        self.credentials['expires_at'] = time.time() + float(result.get('expires_in', 3600))
        self.vault.write(self.credentials)  # Rotierten Refresh-Token sofort sichern.

    def login(self):
        if not self.credentials.get('client_secret'):
            raise AppError('Client-Secret fehlt. Mit --setup neu einrichten.')
        state = secrets.token_urlsafe(32)
        result = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Keine geheimen Autorisierungscodes protokollieren.

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                valid = parsed.path == '/callback' and secrets.compare_digest(query.get('state', [''])[0], state)
                self.send_response(200 if valid else 400)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                if valid:
                    result.update({k: v[0] for k, v in query.items()})
                self.wfile.write(('Anmeldung verarbeitet. Fenster schließen.' if valid else 'Ungültiger Callback.').encode())

        params = dict(client_id=self.client, redirect_uri=REDIRECT, response_type='code',
                      scope='openid offline_access vehicle_charging_cmds', state=state,
                      locale='de-DE', require_requested_scopes='true')
        url = 'https://auth.tesla.com/oauth2/v3/authorize?' + urlencode(params)
        with HTTPServer(('127.0.0.1', 8585), Callback) as server:
            server.timeout = 1
            print('Bitte im Browser bei Tesla anmelden (maximal 5 Minuten).')
            print('Falls sich kein Browser öffnet:\n' + url)
            webbrowser.open(url)
            deadline = time.monotonic() + 300
            while not result and time.monotonic() < deadline:
                server.handle_request()
        if not result.get('code'):
            raise AppError('Anmeldung abgelehnt, abgebrochen oder Zeitlimit erreicht.')
        self.save_tokens(token_request(dict(grant_type='authorization_code', client_id=self.client,
            client_secret=self.credentials['client_secret'], code=result['code'],
            redirect_uri=REDIRECT, audience=self.base)))

    def token(self):
        if self.credentials.get('expires_at', 0) < time.time() + 60:
            refresh = self.credentials.get('refresh_token')
            if not refresh:
                raise AppError('Noch keine Anmeldung. Mit --login starten.')
            self.save_tokens(token_request(dict(grant_type='refresh_token', client_id=self.client,
                                                refresh_token=refresh)))
        return self.credentials['access_token']

    def get(self, path, **params):
        url = self.base + path
        if params:
            url += '?' + urlencode(params)
        return request(url, token=self.token())


def records_from(payload):
    value = payload.get('response', payload) if isinstance(payload, dict) else payload
    if isinstance(value, dict):
        for key in ('data', 'chargingHistory', 'records', 'history'):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise AppError('Unbekanntes Format der Ladehistorie. Abruf möglicherweise unvollständig.')
    return value


def sync(tesla, output, vin=None):
    output.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = pending = failed = 0
    seen = set()
    for page in range(1, 1001):
        params = {'pageNo': page, 'pageSize': 50}
        if vin:
            params['vin'] = vin
        print(f'Ladehistorie: Seite {page}')
        rows = records_from(json.loads(tesla.get('/api/1/dx/charging/history', **params)))
        if not rows:
            break
        fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        if fingerprint in seen:
            raise AppError('Tesla wiederholt eine Seite. Historie möglicherweise unvollständig.')
        seen.add(fingerprint)
        for row in rows:
            if vin and row.get('vin', '').upper() != vin.upper():
                continue
            invoices = row.get('invoices') or []
            if not invoices:
                pending += 1
            for invoice in invoices:
                identifier = invoice.get('contentId') or invoice.get('id')
                if not identifier:
                    pending += 1
                    continue
                identifier = str(identifier)
                name = 'Supercharger_' + hashlib.sha256(identifier.encode()).hexdigest() + '.pdf'
                target = output / name
                if target.exists() and target.read_bytes().startswith(b'%PDF-'):
                    skipped += 1
                    continue
                try:
                    pdf = tesla.get('/api/1/dx/charging/invoice/' + quote(identifier, safe=''))
                    if not pdf.startswith(b'%PDF-'):
                        raise AppError('Antwort enthält keine PDF-Datei.')
                    temporary = target.with_suffix('.pdf.part')
                    temporary.write_bytes(pdf)
                    os.replace(temporary, target)
                    downloaded += 1
                    print('Gespeichert: ' + name)
                except AppError as exc:
                    failed += 1
                    print(f'Rechnung nicht geladen: {exc}', file=sys.stderr)
    else:
        raise AppError('Seitenlimit erreicht; Historie möglicherweise unvollständig.')
    print(f'Fertig: {downloaded} neu, {skipped} vorhanden, {pending} ohne Rechnung, {failed} fehlgeschlagen.')
    if failed:
        raise AppError('Nicht alle Rechnungen geladen. Erneuter Start versucht sie nochmals.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Client-ID und Secret einrichten')
    parser.add_argument('--login', action='store_true', help='Erneut im Browser anmelden')
    parser.add_argument('--output', type=Path, default=ROOT / 'Rechnungen', help='PDF-Zielordner')
    parser.add_argument('--vin', help='Nur Rechnungen dieser Fahrzeugidentifikationsnummer')
    parser.add_argument('--interval', type=int, default=0, metavar='MINUTEN', help='Wiederholung ab 15 Minuten')
    args = parser.parse_args()
    if args.interval and args.interval < 15:
        parser.error('--interval muss mindestens 15 sein.')
    try:
        if args.setup or not CONFIG.exists():
            setup()
        tesla = Tesla(json.loads(CONFIG.read_text(encoding='utf-8')))
        if args.login or not tesla.credentials.get('refresh_token'):
            tesla.login()
        while True:
            sync(tesla, args.output.resolve(), args.vin)
            if not args.interval:
                return 0
            print(f'Nächster Abruf in {args.interval} Minuten. Beenden mit Strg+C.')
            time.sleep(args.interval * 60)
    except KeyboardInterrupt:
        print('\nBeendet.')
        return 0
    except (AppError, OSError, ValueError, KeyError) as exc:
        print(f'Fehler: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
