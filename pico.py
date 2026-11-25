"""Escenario 3: pico de 6 envios simultaneos con Transportista lento.

Muestra el Bulkhead (rechaza el exceso al instante), el timeout (corta a los 2 s)
y el Circuit Breaker (se abre tras 3 fallos y responde de inmediato).

Uso, con el sistema levantado (docker compose up):
    python pico.py

Debe estar en la raiz del repositorio, junto a docker-compose.yml.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GATEWAY = "http://localhost:8000"
REPO = os.path.dirname(os.path.abspath(__file__))
RONDA = str(int(time.time()))  # envio_id distinto en cada ejecucion, para que la idempotencia no oculte el pico


def compose(args: str, lento: str) -> None:
    env = {**os.environ, "TRANSPORTISTA_LENTO": lento}
    subprocess.run(f"docker compose {args}", shell=True, cwd=REPO, env=env)


def http(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(GATEWAY + path, data=data, method=method, headers=headers)
    start = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        code, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        code, raw = exc.code, exc.read()
    return code, json.loads(raw or b"{}"), time.time() - start


def enviar(envio_id):
    code, data, secs = http("POST", "/v1/envios", {"producto_id": 1, "cantidad": 1, "envio_id": envio_id}, token)
    detalle = data.get("detalle", data) if isinstance(data.get("detalle"), dict) else data
    return envio_id, code, secs, detalle.get("detalle_error") or detalle.get("estado")


if not os.path.exists(os.path.join(REPO, "docker-compose.yml")):
    sys.exit("pico.py debe estar en la raiz del repositorio, junto a docker-compose.yml")

print("=== ESCENARIO 3: Transportista lento (5 s), pico de 6 envios ===\n")
print("> TRANSPORTISTA_LENTO=5 docker compose up -d transportista")
compose("up -d transportista", lento="5")
time.sleep(6)

token = http("POST", "/v1/auth/login", {"username": "Patricio Estrella", "password": "star123"})[1]["access_token"]

print("\n> 6 x POST /v1/envios en paralelo")
with ThreadPoolExecutor(max_workers=6) as pool:
    resultados = list(pool.map(enviar, [f"PICO{RONDA}-{i}" for i in range(1, 7)]))
for envio_id, code, secs, motivo in sorted(resultados, key=lambda r: r[2]):
    print(f"{envio_id}: HTTP {code} en {secs:.2f} s | {motivo}")

print("\n> 1 envio mas, con el circuito abierto")
envio_id, code, secs, motivo = enviar(f"EXTRA{RONDA}")
print(f"{envio_id}: HTTP {code} en {secs:.2f} s | {motivo}")

print("\n> GET /v1/resiliencia")
print(json.dumps(http("GET", "/v1/resiliencia", token=token)[1], indent=2))

print("\n> Transportista vuelve a la normalidad")
compose("up -d transportista", lento="0")
