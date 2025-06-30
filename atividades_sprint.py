# Página de Code Review agrupada por User Story (Pai)
import streamlit as st
import os
import base64
import requests
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
import re

load_dotenv()

AZURE_CONFIG = {
    "ORGANIZATION": "iaratech",
    "PROJECT": "Iara",
    "PAT": os.getenv("AZURE_PAT"),
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
        sprint = data['value'][0]
        return sprint['path']

    def get_work_items_by_iteration(self, iteration_path):
        wiql = {
            "query": f"""
                SELECT [System.Id] FROM WorkItems
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
                "Microsoft.VSTS.Scheduling.CompletedWork", "System.State",
                "System.WorkItemType", "System.Parent"
            ]
        }
        response = requests.post(url, headers=self.headers, json=body)
        response.raise_for_status()
        return response.json().get("value", [])

# Inicio
api = AzureDevOpsAPI()
st.set_page_config(layout="wide")
st.title("🧩 Atividade Sprint-116 agrupado por User Story")

# 🔍 Filtro por estado
estado_filtro = st.selectbox(
    "Filtrar atividades por estado:",
    options=["Todos", "To Do", "In Progress", "Code Review", "Done"],
    index=0
)

try:
    iteration = api.get_current_iteration()
    ids = api.get_work_items_by_iteration(iteration)
    detalhes = api.get_work_items_details(ids)

    atividades_por_pai = defaultdict(list)
    dados_pais = {}

    for item in detalhes:
        fields = item['fields']
        tipo = fields.get("System.WorkItemType")
        parent_id = fields.get("System.Parent")
        if tipo == "User Story":
            dados_pais[item['id']] = fields.get("System.Title", f"User Story #{item['id']}")
        else:
            atividades_por_pai[parent_id].append({
                "id": item['id'],
                "title": fields.get("System.Title"),
                "dev": fields.get("System.AssignedTo", {}).get("displayName", "Não atribuído"),
                "horas": fields.get("Microsoft.VSTS.Scheduling.CompletedWork", 0),
                "state": fields.get("System.State"),
                "tipo": tipo,
                "is_code_review": '[Gestão]CodeReview' in fields.get("System.Title", "")
            })

    for pai_id, tarefas in atividades_por_pai.items():
        # Aplicar filtro
        tarefas_filtradas = [
            t for t in tarefas if estado_filtro == "Todos" or t['state'] == estado_filtro
        ]
        if not tarefas_filtradas:
            continue  # pula se nenhuma atividade corresponde ao filtro

        st.markdown(f"""
        <div style='border: 2px solid #ccc; border-radius: 10px; padding: 20px; margin: 15px 0;'>
            <h4 style='margin-bottom: 10px;'>🧠 <b>{dados_pais.get(pai_id, f'User Story #{pai_id}')}</b></h4>
        """, unsafe_allow_html=True)

        for t in tarefas_filtradas:
            cor = "#f0f9ff" if t['is_code_review'] else "#f9f9f9"
            st.markdown(f"""
                <div style='background-color:{cor}; border:1px solid #ddd; border-radius:8px; padding:10px; margin-bottom:10px;'>
                    <b>{t['title']}</b> (#{t['id']})<br>
                    👨‍💻 <b>Dev:</b> {t['dev']} | ⏱️ <b>Horas:</b> {t['horas']} | 📌 <b>Status:</b> {t['state']} | 🏷️ <b>Tipo:</b> {t['tipo']}
                </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

except Exception as e:
    st.error("Erro ao carregar atividades.")
    st.exception(e)
