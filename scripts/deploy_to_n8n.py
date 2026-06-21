#!/usr/bin/env python3
"""
Deploy workflows para o n8n via REST API.

Uso:
  python scripts/deploy_to_n8n.py --api-key SUA_API_KEY

Obter API key: n8n → Settings → API → Create an API key
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Instale requests: pip install requests")
    sys.exit(1)

N8N_BASE_URL = "https://freitasgoulartgomesa.app.n8n.cloud"
WORKFLOWS_DIR = Path(__file__).parent.parent / "n8n_workflows"
WORKFLOW_FILES = [
    "alerta_sinal_telegram.json",
    "relatorio_diario.json",
    "monitor_posicao.json",
]


def get_headers(api_key: str) -> dict:
    return {
        "X-N8N-API-KEY": api_key,
        "Content-Type": "application/json",
    }


def list_existing_workflows(api_key: str) -> dict:
    r = requests.get(f"{N8N_BASE_URL}/api/v1/workflows", headers=get_headers(api_key))
    r.raise_for_status()
    return {w["name"]: w["id"] for w in r.json().get("data", [])}


def create_or_update_workflow(api_key: str, workflow: dict, existing: dict) -> str:
    name = workflow["name"]
    if name in existing:
        wf_id = existing[name]
        print(f"  Atualizando '{name}' (id={wf_id})...")
        r = requests.put(
            f"{N8N_BASE_URL}/api/v1/workflows/{wf_id}",
            headers=get_headers(api_key),
            json=workflow,
        )
    else:
        print(f"  Criando '{name}'...")
        r = requests.post(
            f"{N8N_BASE_URL}/api/v1/workflows",
            headers=get_headers(api_key),
            json=workflow,
        )
    r.raise_for_status()
    return r.json()["id"]


def activate_workflow(api_key: str, wf_id: str, name: str):
    r = requests.post(
        f"{N8N_BASE_URL}/api/v1/workflows/{wf_id}/activate",
        headers=get_headers(api_key),
    )
    if r.status_code == 200:
        print(f"  ✅ '{name}' ativado")
    else:
        print(f"  ⚠️  '{name}' criado mas não ativado automaticamente (ative manualmente no n8n)")
        print(f"      Motivo: {r.text[:200]}")


def main():
    parser = argparse.ArgumentParser(description="Deploy workflows para o n8n")
    parser.add_argument("--api-key", required=True, help="API key do n8n")
    parser.add_argument(
        "--no-activate", action="store_true", help="Não ativar workflows após deploy"
    )
    args = parser.parse_args()

    print(f"\n🚀 Conectando em {N8N_BASE_URL}...")

    try:
        existing = list_existing_workflows(args.api_key)
        print(f"   Workflows existentes: {list(existing.keys()) or 'nenhum'}\n")
    except requests.HTTPError as e:
        print(f"❌ Erro ao conectar: {e}")
        print("   Verifique se a API key está correta (n8n → Settings → API)")
        sys.exit(1)

    deployed = []
    for filename in WORKFLOW_FILES:
        path = WORKFLOWS_DIR / filename
        if not path.exists():
            print(f"⚠️  Arquivo não encontrado: {path}")
            continue

        workflow = json.loads(path.read_text())
        print(f"📋 {filename}")
        try:
            wf_id = create_or_update_workflow(args.api_key, workflow, existing)
            if not args.no_activate:
                activate_workflow(args.api_key, wf_id, workflow["name"])
            deployed.append(workflow["name"])
        except requests.HTTPError as e:
            print(f"  ❌ Erro: {e.response.text[:300]}")

    print(f"\n✅ Deploy concluído: {len(deployed)}/{len(WORKFLOW_FILES)} workflows")
    print("\n📌 Próximo passo obrigatório:")
    print("   Em cada workflow no n8n, abra os nós do Telegram e selecione")
    print("   a credencial 'Telegram account' (não é possível definir via API).")
    print(f"\n🔗 Acesse: {N8N_BASE_URL}/home/workflows")


if __name__ == "__main__":
    main()
