# Página de análise de Code Review com 3 cards
import streamlit as st
import os
import base64
import requests
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

AZURE_CONFIG = {
    "ORGANIZATION": "iaratech",
    "PROJECT": "Iara",
    "PAT": os.getenv("AZURE_PAT"),
    "WORKING_HOURS_PER_DAY": 7,
    "DEFAULT_DEV_COUNT": 5
}

class AzureDevOpsAPI:
    def __init__(self):
        self.headers = self._create_headers()

    def _create_headers(self):
        encoded_pat = base64.b64encode(f":{AZURE_CONFIG['PAT']}".encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded_pat}"
        }

    def get_current_iteration(self):
        url = f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/work/teamsettings/iterations?$timeframe=current&api-version=6.0"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        data = response.json()
        if not data['value']:
            raise Exception("Nenhuma sprint atual encontrada.")
        sprint = data['value'][0]
        start = datetime.strptime(sprint['attributes']['startDate'], '%Y-%m-%dT%H:%M:%SZ')
        end = datetime.strptime(sprint['attributes']['finishDate'], '%Y-%m-%dT%H:%M:%SZ')
        return sprint['path'], start, end

    def get_work_items_by_iteration(self, iteration_path):
        wiql = {
            "query": f"""
                SELECT [System.Id]
                FROM WorkItems
                WHERE [System.TeamProject] = '{AZURE_CONFIG['PROJECT']}'
                AND [System.IterationPath] = '{iteration_path}'
                AND [System.WorkItemType] IN ('User Story', 'Task', 'Bug')
            """
        }
        url = f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/wiql?api-version=6.0"
        response = requests.post(url, headers=self.headers, json=wiql)
        response.raise_for_status()
        return [item["id"] for item in response.json().get("workItems", [])]

    def get_work_items_details(self, ids):
        if not ids:
            return []
        url = f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/workitemsbatch?api-version=6.0"
        body = {
            "ids": ids,
            "fields": [
                "System.Id", "System.Title", "System.AssignedTo",
                "Microsoft.VSTS.Scheduling.CompletedWork", "System.State", "System.WorkItemType"
            ]
        }
        response = requests.post(url, headers=self.headers, json=body)
        response.raise_for_status()
        return response.json().get("value", [])

# Instanciar API e carregar dados
api = AzureDevOpsAPI()
st.title("🛠️ Análise Completa de Code Review (3 Cards)")
import re

try:
    iteration_path, _, _ = api.get_current_iteration()
    work_items_raw = api.get_work_items_by_iteration(iteration_path)
    all_details = api.get_work_items_details(work_items_raw)

    atividades_code_review = []
    atividades_real = []

    for item in all_details:
        title = item['fields'].get('System.Title', '')

        # Detectar code review
        if '[Gestão]CodeReview - Tipo:' in title:
            match = re.search(r'Atividade Nº[:\s]*(\d+)', title)
            if match:
                id_ref = int(match.group(1))
                atividades_code_review.append({
                    "id": item['id'],
                    "tipo": item['fields'].get('System.WorkItemType'),
                    "state": item['fields'].get('System.State'),
                    "title": title,
                    "referencia": id_ref,
                    "horas_code_review": item['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0),
                    "dev": item['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído')
                })

        # Detectar atividades reais em estado Code Review
        elif item['fields'].get('System.State') == 'Code Review':
            atividades_real.append({
                "id": item['id'],
                "dev": item['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído'),
                "title": title,
                "horas": item['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0),
                "state": item['fields'].get('System.State')
            })

    st.subheader("📘 Atividades reais em estado 'Code Review'")
    for atividade in atividades_real:
        with st.container():
            st.markdown(f"### {atividade['title']} (#{atividade['id']})")
            st.markdown(f"👨‍💻 **Desenvolvedor:** {atividade['dev']}")
            st.markdown(f"⏱️ **Horas apontadas:** {atividade['horas']}")
            st.markdown(f"📌 **Status:** {atividade['state']}")
            st.markdown("---")

    st.subheader("📗 Atividades de [Gestão]CodeReview")
    for code in atividades_code_review:
        with st.container():
            st.markdown(f"### {code['title']} (#{code['id']})")
            st.markdown(f"🔗 **Referência:** {code['referencia']}")
            st.markdown(f"👨‍💻 **Desenvolvedor:** {code['dev']}")
            st.markdown(f"📊 **Horas Code Review:** {code['horas_code_review']} | 📌 **Estado:** {code['state']}")
            st.markdown("---")

    st.subheader("📙 Comparativo entre Code Review e Atividade Referenciada")
    for cr in atividades_code_review:
        ref_id = cr["referencia"]
        atividade_ref = next((a for a in atividades_real if a["id"] == ref_id), None)
        if atividade_ref:
            with st.container():
                st.markdown(f"### 🔗 Referência: {ref_id} - {atividade_ref['title']} (#{ref_id})")
                st.markdown(f"🧪 **Code Review:** {cr['title']} (#{cr['id']})")
                st.markdown(f"⏱️ **Horas Code Review:** {cr['horas_code_review']} | **Status Code Review:** {cr['state']}")
                st.markdown(f"💻 **Horas Desenvolvimento:** {atividade_ref['horas']} | **Status Atividade:** {atividade_ref['state']}")
                st.markdown("---")

    ids_referenciados = set(c['referencia'] for c in atividades_code_review)
    st.subheader("🚨 Atividades em 'Code Review' sem [Gestão]CodeReview correspondente")
    faltando = [a for a in atividades_real if a['id'] not in ids_referenciados]
    for atividade in faltando:
        with st.container():
            st.markdown(f"🚨 **{atividade['title']}** (#{atividade['id']})")
            st.markdown(f"👨‍💻 **Desenvolvedor:** {atividade['dev']}")
            st.markdown(f"⏱️ **Horas:** {atividade['horas']}")
            st.markdown("---")

except Exception as e:
    st.error("Erro ao carregar dados da sprint atual.")
    st.exception(e)