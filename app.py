import requests
from collections import defaultdict
import streamlit as st
import base64
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import os


# Constants
FERIADOS = [
    '01-01', '07-09', '25-12', '01-05',  # Nacionais
    '25-01', '09-07',                    # SP
    '19-03', '15-08'                     # Ribeirão Preto
]

AZURE_CONFIG = {
    "ORGANIZATION": "iaratech",
    "PROJECT": "Iara",
    "PAT": os.getenv("AZURE_PAT"),
    "WORKING_HOURS_PER_DAY": 7,
    "DEFAULT_DEV_COUNT": 5
}



# Azure DevOps API Utilities
class AzureDevOpsAPI:
    def __init__(self):
        self.headers = self._create_headers()
        
    def _create_headers(self):
        encoded_pat = base64.b64encode(f":{AZURE_CONFIG['PAT']}".encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded_pat}"
        }
    def get_all_iterations(self):
        url = f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/work/teamsettings/iterations?api-version=6.0"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json().get("value", [])

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

    def get_work_item_ids(self, iteration_path):
        wiql = {
            "query": f"""
                SELECT [System.Id], [Microsoft.VSTS.Scheduling.OriginalEstimate], [Microsoft.VSTS.Scheduling.CompletedWork]
                FROM WorkItems
                WHERE [System.TeamProject] = '{AZURE_CONFIG['PROJECT']}'
                  AND [System.IterationPath] = '{iteration_path}'
                  AND [System.WorkItemType] IN ('User Story', 'Task', 'Bug')
            """
        }
        response = requests.post(
            f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/wiql?api-version=6.0",
            headers=self.headers, json=wiql)
        response.raise_for_status()
        data = response.json()
        return [(item['id'],
                 item.get('fields', {}).get('Microsoft.VSTS.Scheduling.OriginalEstimate', 0),
                 item.get('fields', {}).get('Microsoft.VSTS.Scheduling.CompletedWork', 0))
                for item in data.get('workItems', [])]

    def get_work_items_details(self, ids_with_estimates):
        if not ids_with_estimates:
            return []

        ids = [item[0] for item in ids_with_estimates]
        url = f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/workitemsbatch?api-version=6.0"
        body = {
            "ids": ids,
            "fields": [
                "System.Id", "System.Title", "System.AssignedTo",
                "Microsoft.VSTS.Scheduling.CompletedWork", "Microsoft.VSTS.Scheduling.OriginalEstimate",
                "System.WorkItemType", "System.State"
            ]
        }
        response = requests.post(url, headers=self.headers, json=body)
        response.raise_for_status()

        items = response.json().get('value', [])
        estimate_map = {item[0]: item[1] for item in ids_with_estimates}

        for item in items:
            item_id = item['id']
            if 'fields' not in item:
                item['fields'] = {}
            item['fields']['Microsoft.VSTS.Scheduling.OriginalEstimate'] = estimate_map.get(item_id, 0)

        return items
    
    
    
    def get_user_stories_with_task_hours(self, iteration_path):
        wiql = {
            "query": f"""
                SELECT [System.Id], [System.Title], [System.State], [System.AssignedTo]
                FROM WorkItems
                WHERE [System.TeamProject] = '{AZURE_CONFIG['PROJECT']}'
                  AND [System.IterationPath] = '{iteration_path}'
                  AND [System.WorkItemType] = 'User Story'
            """
        }
        response = requests.post(
            f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/wiql?api-version=6.0",
            headers=self.headers, json=wiql)
        response.raise_for_status()
        story_data = response.json().get("workItems", [])

        story_ids = [item["id"] for item in story_data]
        if not story_ids:
            return []

        response = requests.post(
            f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/workitemsbatch?api-version=6.0",
            headers=self.headers,
            json={"ids": story_ids, "fields": ["System.Id", "System.Title", "System.State", "System.AssignedTo"]}
        )
        response.raise_for_status()
        stories = response.json().get("value", [])

        result = []
        for story in stories:
            story_id = story["id"]
            story_title = story["fields"].get("System.Title", "")
            story_state = story["fields"].get("System.State", "")
            story_dev = story["fields"].get("System.AssignedTo", {}).get("displayName", "Não atribuído")

            rels = requests.get(
                f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/workitems/{story_id}?$expand=relations&api-version=6.0",
                headers=self.headers
            )
            rels.raise_for_status()
            relations = rels.json().get("relations", [])
            task_ids = [int(r["url"].split("/")[-1]) for r in relations if "System.LinkTypes.Hierarchy-Forward" in r.get("rel", "")]

            if not task_ids:
                total_hours = 0
            else:
                task_batch = requests.post(
                    f"https://dev.azure.com/{AZURE_CONFIG['ORGANIZATION']}/{AZURE_CONFIG['PROJECT']}/_apis/wit/workitemsbatch?api-version=6.0",
                    headers=self.headers,
                    json={"ids": task_ids, "fields": ["Microsoft.VSTS.Scheduling.CompletedWork"]}
                )
                task_batch.raise_for_status()
                tasks = task_batch.json().get("value", [])
                total_hours = sum(t.get("fields", {}).get("Microsoft.VSTS.Scheduling.CompletedWork", 0) for t in tasks)

            result.append({
                "id": story_id,
                "title": story_title,
                "state": story_state,
                "dev": story_dev,
                "completed_work": total_hours
            })

        return result
def mostrar_card_performance(work_items):
    st.markdown("## 📈 Performance da Sprint")
    tasks = [wi for wi in work_items if wi['fields'].get('System.WorkItemType') == 'Task']
    planejadas = [t for t in tasks if '[nãoplanejada]' not in t['fields'].get('System.Title', '').lower()]
    nao_planejadas = [t for t in tasks if '[nãoplanejada]' in t['fields'].get('System.Title', '').lower()]

    planejadas_done = [t for t in planejadas if t['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]
    nao_planejadas_done = [t for t in nao_planejadas if t['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]

    total_tasks_done = [t for t in tasks if t['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]

    # Cálculos
    total_planejadas = len(planejadas)
    total_planejadas_done = len(planejadas_done)
    total_nao_planejadas = len(nao_planejadas)
    total_nao_planejadas_done = len(nao_planejadas_done)
    total_done = len(total_tasks_done)

    perf_planejadas = (total_planejadas_done / total_planejadas * 100) if total_planejadas else 0
    perf_nao_planejadas = (total_nao_planejadas_done / total_nao_planejadas * 100) if total_nao_planejadas else 0
    perf_geral = (total_done / (total_planejadas + total_nao_planejadas) * 100) if (total_planejadas + total_nao_planejadas) else 0

    st.markdown("### 📊 Resultados da Sprint")
    st.write(f"**Total de Tasks Planejadas:** {total_planejadas}")
    st.write(f"**Total de Tasks Done:** {total_done}")
    st.write(f"**Performance Geral:** {perf_geral:.1f}%")

    st.markdown("### ✅ Total Planejado")
    st.write(f"**Quantidade de Tasks Planejadas:** {total_planejadas}")
    st.write(f"**Quantidade de Planejadas Done:** {total_planejadas_done}")
    st.write(f"**Performance Planejadas:** {perf_planejadas:.1f}%")

    st.markdown("### ⚠️ Total Não Planejado")
    st.write(f"**Quantidade de Tasks Não Planejadas:** {total_nao_planejadas}")
    st.write(f"**Quantidade de Não Planejadas Done:** {total_nao_planejadas_done}")
    st.write(f"**Performance Não Planejadas:** {perf_nao_planejadas:.1f}%")
    

# Adição no Dashboard (interface)
def exibir_atividades_nao_planejadas(grouped_data):
    st.markdown("## 🔧 Atividades Não Planejadas")
    rows = []
    for dev, dados in grouped_data.items():
        for item in dados["items"]:
            if "[nãoplanejada]" in item["title"].lower():
                rows.append({
                    "ID": item["id"],
                    "Título": item["title"],
                    "Status": item["state"],
                    "Desenvolvedor": dev,
                    "Horas Trabalhadas": item["completed_work"]
                })
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df)
    else:
        st.write("✅ Nenhuma atividade não planejada encontrada.")

def exibir_atividades_sustentacao(grouped_data):
    st.markdown("## 🛠️ Atividades de Sustentação")
    rows = []
    for dev, dados in grouped_data.items():
        for item in dados["items"]:
            if "[sustentação]" in item["title"].lower():
                rows.append({
                    "ID": item["id"],
                    "Título": item["title"],
                    "Status": item["state"],
                    "Desenvolvedor": dev,
                    "Horas Trabalhadas": item["completed_work"]
                })
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df)
    else:
        st.write("✅ Nenhuma atividade de sustentação encontrada.")
# HTML Export Function

def gerar_html_cards(grouped_data, sprint_title, periodo, dias_uteis):
    html = f"""
    <html><head><meta charset='UTF-8'>
    <style>
    body {{ font-family: Arial; }}
    .card {{ border: 1px solid #ccc; border-radius: 12px; padding: 16px; margin-bottom: 20px; background-color: #f9f9f9; }}
    ul {{ list-style: none; padding: 0; }}
    li {{ margin-bottom: 4px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
    </style></head><body>
    <h1>Relatório de Sprint</h1>
    <h3>{sprint_title}</h3>
    <p><strong>Período:</strong> {periodo}</p>
    """

    for dev, dados in grouped_data.items():
        total_itens = len(dados["items"])
        horas_planejadas = dias_uteis * 7
        nao_planejadas = [i for i in dados["items"] if "[nãoplanejada]" in i["title"].lower()]
        concluidos = [i for i in dados["items"] if i["state"].lower() in ["done", "concluído", "finalizado"]]
        horas_trabalhadas = sum(i["completed_work"] for i in dados["items"] if i["completed_work"] is not None)
        itens_planejados = total_itens - len(nao_planejadas)
        itens_concluidos = len(concluidos)
        performance = (itens_concluidos / itens_planejados * 100) if itens_planejados else 0
        diferenca_horas = horas_trabalhadas - horas_planejadas

        html += f"""
        <div class='card'>
            <h2>👤 {dev}</h2>
            <ul>
                <li><strong>Total de Itens:</strong> {total_itens}</li>
                <li><strong>Horas Planejadas:</strong> {horas_planejadas}</li>
                <li><strong>Atividades Planejadas:</strong> {itens_planejados}</li>
                <li><strong>Atividades Não Planejadas:</strong> {len(nao_planejadas)}</li>
                <li><strong>Itens Concluídos:</strong> {itens_concluidos}</li>
                <li><strong>Horas Trabalhadas:</strong> {horas_trabalhadas:.1f}</li>
                <li><strong>Diferença de Horas:</strong> {diferenca_horas:+.1f}h</li>
                <li><strong>Performance:</strong> {performance:.1f}%</li>
            </ul>
            <table>
                <thead><tr>
                    <th>ID</th><th>Título</th><th>Tipo</th><th>Status</th><th>Horas Trabalhadas</th>
                </tr></thead>
                <tbody>
        """
        for item in dados["items"]:
            html += f"<tr><td>{item['id']}</td><td>{item['title']}</td><td>{item['tipo']}</td><td>{item['state']}</td><td>{item['completed_work']}</td></tr>"
        html += "</tbody></table></div>"

    html += "</body></html>"
    return html

    # Função adicional para mostrar user stories

def mostrar_card_userstories(user_stories):
    st.markdown("## 📘 User Stories da Sprint")

    story_info = []
    for us in user_stories:
        story_info.append({
            'ID': us['id'],
            'Título': us['title'],
            'Status': us['state'],
            'Desenvolvedor': us['dev'],
            'Horas Trabalhadas': us['completed_work']
        })

    st.write(f"Total de User Stories: {len(story_info)}")
    df_us = pd.DataFrame(story_info)
    st.dataframe(df_us)

def mostrar_card_tasks_done(work_items):
    st.markdown("## ✅ Tasks Concluídas")
    done_tasks = [wi for wi in work_items if wi['fields'].get('System.WorkItemType') == 'Task' and wi['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]

    task_info = []
    for task in done_tasks:
        task_info.append({
            'ID': task['id'],
            'Título': task['fields'].get('System.Title', ''),
            'Status': task['fields'].get('System.State', ''),
            'Desenvolvedor': task['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído'),
            'Horas Trabalhadas': task['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0)
        })

    st.write(f"Total de Tasks Done: {len(task_info)}")
    df_tasks = pd.DataFrame(task_info)
    st.dataframe(df_tasks)


def mostrar_card_bugs(work_items):
    st.markdown("## 🐞 Bugs da Sprint")
    bugs = [wi for wi in work_items if wi['fields'].get('System.WorkItemType') == 'Bug']

    bug_info = []
    total_horas = 0
    for bug in bugs:
        horas = bug['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0)
        total_horas += horas
        bug_info.append({
            'ID': bug['id'],
            'Título': bug['fields'].get('System.Title', ''),
            'Status': bug['fields'].get('System.State', ''),
            'Desenvolvedor': bug['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído'),
            'Horas Trabalhadas': horas
        })

    st.write(f"Total de Bugs: {len(bug_info)}")
    st.write(f"Horas trabalhadas nos bugs: {total_horas:.1f}h")
    df_bugs = pd.DataFrame(bug_info)
    st.dataframe(df_bugs)


# Versão para HTML exportado

def gerar_html_userstories_card(user_stories):
    html = """
    <div class='card'>
        <h2>📦 User Stories da Sprint</h2>
        <p><strong>Total de User Stories:</strong> %d</p>
        <table>
            <thead><tr>
                <th>ID</th><th>Título</th><th>Status</th><th>Desenvolvedor</th><th>Horas Trabalhadas</th>
            </tr></thead>
            <tbody>
    """ % len(user_stories)

    for us in user_stories:
        html += f"<tr><td>{us['id']}</td><td>{us['title']}</td><td>{us['state']}</td><td>{us['dev']}</td><td>{us['completed_work']}</td></tr>"

    html += "</tbody></table></div>"
    return html

def gerar_html_tasks_done_card(work_items):
    done_tasks = [wi for wi in work_items if wi['fields'].get('System.WorkItemType') == 'Task' and wi['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]
    html = f"""
    <div class='card'>
        <h2>✅ Tasks Concluídas</h2>
        <p><strong>Total de Tasks Done:</strong> {len(done_tasks)}</p>
        <table>
            <thead><tr>
                <th>ID</th><th>Título</th><th>Status</th><th>Desenvolvedor</th><th>Horas Trabalhadas</th>
            </tr></thead><tbody>
    """
    for task in done_tasks:
        html += f"<tr><td>{task['id']}</td><td>{task['fields'].get('System.Title', '')}</td><td>{task['fields'].get('System.State', '')}</td><td>{task['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído')}</td><td>{task['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0)}</td></tr>"
    html += "</tbody></table></div>"
    return html


def gerar_html_bugs_card(work_items):
    bugs = [wi for wi in work_items if wi['fields'].get('System.WorkItemType') == 'Bug']
    total_horas = sum(bug['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0) for bug in bugs)
    html = f"""
    <div class='card'>
        <h2>🐞 Bugs da Sprint</h2>
        <p><strong>Total de Bugs:</strong> {len(bugs)}</p>
        <p><strong>Horas trabalhadas nos bugs:</strong> {total_horas:.1f}h</p>
        <table>
            <thead><tr>
                <th>ID</th><th>Título</th><th>Status</th><th>Desenvolvedor</th><th>Horas Trabalhadas</th>
            </tr></thead><tbody>
    """
    for bug in bugs:
        html += f"<tr><td>{bug['id']}</td><td>{bug['fields'].get('System.Title', '')}</td><td>{bug['fields'].get('System.State', '')}</td><td>{bug['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído')}</td><td>{bug['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0)}</td></tr>"
    html += "</tbody></table></div>"
    return html
def gerar_html_sustentacao_card(grouped_data):
    atividades_sustentacao = [
        (item['id'], item['title'], item['state'], dev, item['completed_work'])
        for dev, dados in grouped_data.items()
        for item in dados['items']
        if '[sustentação]' in item['title'].lower()
    ]

    total = len(atividades_sustentacao)
    total_horas = sum(item[4] for item in atividades_sustentacao if item[4] is not None)

    html = f"""
    <div class='card'>
        <h2>🛠️ Atividades de Sustentação</h2>
        <p><strong>Total de Itens:</strong> {total} | <strong>Horas Trabalhadas:</strong> {total_horas:.1f}h</p>
        <table>
            <thead><tr>
                <th>ID</th><th>Título</th><th>Status</th><th>Desenvolvedor</th><th>Horas Trabalhadas</th>
            </tr></thead>
            <tbody>
    """
    for item in atividades_sustentacao:
        html += f"<tr><td>{item[0]}</td><td>{item[1]}</td><td>{item[2]}</td><td>{item[3]}</td><td>{item[4]}</td></tr>"

    html += "</tbody></table></div>"
    return html

def gerar_html_performance_card(work_items):
    tasks = [wi for wi in work_items if wi['fields'].get('System.WorkItemType') == 'Task']
    planejadas = [t for t in tasks if '[nãoplanejada]' not in t['fields'].get('System.Title', '').lower()]
    nao_planejadas = [t for t in tasks if '[nãoplanejada]' in t['fields'].get('System.Title', '').lower()]

    planejadas_done = [t for t in planejadas if t['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]
    nao_planejadas_done = [t for t in nao_planejadas if t['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]

    total_tasks_done = [t for t in tasks if t['fields'].get('System.State', '').lower() in ['done', 'concluído', 'finalizado']]

    total_planejadas = len(planejadas)
    total_planejadas_done = len(planejadas_done)
    total_nao_planejadas = len(nao_planejadas)
    total_nao_planejadas_done = len(nao_planejadas_done)
    total_done = len(total_tasks_done)

    perf_planejadas = (total_planejadas_done / total_planejadas * 100) if total_planejadas else 0
    perf_nao_planejadas = (total_nao_planejadas_done / total_nao_planejadas * 100) if total_nao_planejadas else 0
    perf_geral = (total_done / (total_planejadas + total_nao_planejadas) * 100) if (total_planejadas + total_nao_planejadas) else 0

    html = f"""
    <div class='card'>
        <h2>📈 Performance da Sprint</h2>
        <h3>📊 Resultados da Sprint</h3>
        <p><strong>Total de Tasks Planejadas:</strong> {total_planejadas}</p>
        <p><strong>Total de Tasks Done:</strong> {total_done}</p>
        <p><strong>Performance Geral:</strong> {perf_geral:.1f}%</p>

        <h3>✅ Total Planejado</h3>
        <p><strong>Quantidade de Tasks Planejadas:</strong> {total_planejadas}</p>
        <p><strong>Quantidade de Planejadas Done:</strong> {total_planejadas_done}</p>
        <p><strong>Performance Planejadas:</strong> {perf_planejadas:.1f}%</p>

        <h3>⚠️ Total Não Planejado</h3>
        <p><strong>Quantidade de Tasks Não Planejadas:</strong> {total_nao_planejadas}</p>
        <p><strong>Quantidade de Não Planejadas Done:</strong> {total_nao_planejadas_done}</p>
        <p><strong>Performance Não Planejadas:</strong> {perf_nao_planejadas:.1f}%</p>
    </div>
    """
    return html

def exibir_atividades_sustentacao(grouped_data):
    st.markdown("## 🛠️ Atividades de Sustentação")
    rows = []
    for dev, dados in grouped_data.items():
        for item in dados["items"]:
            if "[sustentação]" in item["title"].lower():
                rows.append({
                    "ID": item["id"],
                    "Título": item["title"],
                    "Status": item["state"],
                    "Desenvolvedor": dev,
                    "Horas Trabalhadas": item["completed_work"]
                })
    
    if rows:
        df = pd.DataFrame(rows)
        total_horas = df["Horas Trabalhadas"].sum()
        st.markdown(f"**Total de Atividades:** {len(rows)} | Horas Trabalhadas:**{total_horas:.1f}h**")
        st.dataframe(df)
    else:
        st.success("✅ Nenhuma atividade de sustentação encontrada.")

# Business Logic
class SprintAnalyzer:
    @staticmethod
    def calcular_dias_uteis(inicio, fim):
        """Calcula dias úteis excluindo finais de semana e feriados"""
        datas = pd.date_range(start=inicio, end=fim, freq='B')
        return sum(1 for data in datas if data.strftime('%d-%m') not in FERIADOS)
    
    @staticmethod
    def calcular_metricas_gerais(work_items, inicio_sprint, fim_sprint):
        total_completed = sum(1 for wi in work_items if wi['fields'].get('System.State', '').lower() == 'done')
        total_items = len(work_items)
        dias_uteis = SprintAnalyzer.calcular_dias_uteis(inicio_sprint, fim_sprint)
        total_estimated = dias_uteis * AZURE_CONFIG['WORKING_HOURS_PER_DAY'] * AZURE_CONFIG['DEFAULT_DEV_COUNT']
        total_worked = sum(wi['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0) for wi in work_items)
        
        return {
            "total_items": total_items,
            "completed_items": total_completed,
            "completion_rate": (total_completed / total_items * 100) if total_items else 0,
            "total_estimated": total_estimated,
            "total_worked": total_worked,
            "efficiency": (total_worked / total_estimated * 100) if total_estimated else 0
        }
    
    @staticmethod
    def agrupar_por_dev(work_items, inicio_sprint, fim_sprint):
        por_dev = defaultdict(lambda: {
            "total_completed_work": 0,
            "total_original_estimate": 0,
            "items": [],
            "completed_items": 0,
            "total_items": 0
        })

        dias_uteis = SprintAnalyzer.calcular_dias_uteis(inicio_sprint, fim_sprint)
        horas_por_dev = dias_uteis * AZURE_CONFIG['WORKING_HOURS_PER_DAY']

        for wi in work_items:
            if wi['fields'].get('System.WorkItemType', '') == 'User Story':
                continue
            dev = wi['fields'].get('System.AssignedTo', {}).get('displayName', 'Não atribuído')
            completed_work = wi['fields'].get('Microsoft.VSTS.Scheduling.CompletedWork', 0)
            state = wi['fields'].get('System.State', '')
            
            por_dev[dev]["total_completed_work"] += completed_work or 0
            por_dev[dev]["total_items"] += 1
            if state.lower() == 'done':
                por_dev[dev]["completed_items"] += 1
                
            por_dev[dev]["items"].append({
                "id": wi['id'],
                "title": wi['fields'].get('System.Title', ''),
                "tipo": wi['fields'].get('System.WorkItemType', ''),
                "completed_work": completed_work or 0,
                "state": state,
                "deviation": 0
            })

        # Atribui as horas fixas por desenvolvedor (7h/dia * dias úteis)
        for dev, dados in por_dev.items():
            dados["total_original_estimate"] = horas_por_dev
            
            if dados["total_items"] > 0:
                estimate_por_item = round(horas_por_dev / dados["total_items"], 1)
                for item in dados["items"]:
                    item["original_estimate"] = estimate_por_item
                    item["deviation"] = round(item["completed_work"] - estimate_por_item, 1)
                    
        return por_dev

# Visualization
class Dashboard:
    @staticmethod
    def show_metrics(metrics):
        st.markdown("## 📈 Métricas Gerais da Sprint")
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric("Total de Itens", metrics["total_items"])
        with col2: st.metric("Concluídos", metrics["completed_items"])
        with col3: st.metric("Horas Estimadas", round(metrics["total_estimated"], 1))
        with col4: st.metric("Horas Trabalhadas", round(metrics["total_worked"], 1))
        
        st.metric("Eficiência (%)", f"{metrics['efficiency']:.1f}%")
        st.metric("Taxa de Conclusão (%)", f"{metrics['completion_rate']:.1f}%")
    
    @staticmethod
    def show_dev_details(grouped_data, dias_uteis):
        st.markdown("## 👨‍💻 Detalhamento por Desenvolvedor")
        for dev, dados in grouped_data.items():
            with st.expander(f"👤 {dev}"):
                total_itens = len(dados["items"])
                horas_planejadas = dias_uteis * 7
                nao_planejadas = [item for item in dados["items"] if "[nãoplanejada]" in item["title"].lower()]
                concluidos = [item for item in dados["items"] if item["state"].lower() in ["done", "concluído", "finalizado"]]
                horas_trabalhadas = sum(item["completed_work"] for item in dados["items"] if item["completed_work"] is not None)

                itens_planejados = total_itens - len(nao_planejadas)
                itens_concluidos = len(concluidos)
                performance = (itens_concluidos / itens_planejados) * 100 if itens_planejados else 0

                if performance >= 100:
                    icone = "💡"
                elif performance >= 90:
                    icone = "🚀"
                else:
                    icone = "⚠️"

                diferenca_horas = horas_trabalhadas - horas_planejadas

                card_html = f"""
                    <div style="border: 1px solid #ccc; border-radius: 12px; padding: 16px; margin: 10px 0; background-color: #f9f9f9;">
                        <h4>👤 {dev}</h4>
                        <ul style="list-style-type: none; padding-left: 0; line-height: 1.8;">
                            <li><strong>Total de Itens:</strong> {total_itens}</li>
                            <li><strong>Horas Planejadas:</strong> {horas_planejadas}</li>
                            <li><strong>Atividades Planejadas:</strong> {itens_planejados}</li>
                            <li><strong>Atividades Não Planejadas:</strong> {len(nao_planejadas)}</li>
                            <li><strong>Itens Concluídos:</strong> {itens_concluidos}</li>
                            <li><strong>Horas Trabalhadas:</strong> {horas_trabalhadas:.1f}</li>
                            <li><strong>Diferença de Horas:</strong> {diferenca_horas:+.1f}h</li>
                            <li><strong>Performance:</strong> {performance:.1f}% {icone}</li>
                        </ul>
                    </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)
                st.progress(min(performance / 100, 1.0))

                df = pd.DataFrame(dados["items"])
                st.dataframe(df[["id", "title", "tipo", "state", "completed_work"]])
    
    @staticmethod
    def show_comparison_chart(grouped_data):
        st.markdown("## 📊 Comparativo: Estimado vs Trabalhado")
        devs = []
        estimadas = []
        realizadas = []
        diferencas = []

        for dev, dados in grouped_data.items():
            devs.append(dev)
            estimadas.append(dados["total_original_estimate"])
            realizadas.append(dados["total_completed_work"])
            diferencas.append(dados["total_completed_work"] - dados["total_original_estimate"])

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
        
        # Gráfico de barras comparativo
        bar_largura = 0.35
        indices = range(len(devs))
        ax1.bar(indices, estimadas, width=bar_largura, label='Estimado (7h/dia)', color='skyblue')
        ax1.bar([i + bar_largura for i in indices], realizadas, width=bar_largura, 
              label='Trabalhado', color='orange')
        ax1.set_xticks([i + bar_largura / 2 for i in indices])
        ax1.set_xticklabels(devs, rotation=45)
        ax1.set_ylabel("Horas")
        ax1.set_title("Horas Estimadas vs Trabalhadas")
        ax1.legend()

        # Gráfico de diferenças
        colors = ['green' if diff >= 0 else 'red' for diff in diferencas]
        ax2.bar(devs, diferencas, color=colors)
        ax2.axhline(0, color='black', linewidth=0.8)
        ax2.set_title("Diferença (Trabalhado - Estimado)")
        ax2.set_ylabel("Horas")
        ax2.tick_params(axis='x', rotation=45)

        plt.tight_layout()
        st.pyplot(fig)
def create_sprint_selector(api):
    all_iterations = api.get_all_iterations()
    
    # Filtra apenas as iterações com data de início válida
    all_iterations = [it for it in all_iterations if it["attributes"].get("startDate")]

    # Ordena por data de início
    all_iterations.sort(key=lambda it: it["attributes"]["startDate"])

    # Pega a sprint atual
    current_path, _, _ = api.get_current_iteration()
    current_index = next(i for i, it in enumerate(all_iterations) if it["path"] == current_path)

    # Seleciona 2 anteriores, a atual e 2 futuras
    start = max(current_index - 2, 0)
    end = min(current_index + 3, len(all_iterations))
    visible_sprints = all_iterations[start:end]

    sprint_names = [it["name"] for it in visible_sprints]
    default_index = next(i for i, it in enumerate(visible_sprints) if it["path"] == current_path)

    selected_name = st.selectbox("📅 Selecione a Sprint", sprint_names, index=default_index)
    selected_path = next(it["path"] for it in visible_sprints if it["name"] == selected_name)

    return selected_path
# Main Application
def main():
    st.set_page_config(layout="wide")
    st.title("📊 Sprint Review Dashboard")

    azure_api = AzureDevOpsAPI()
    analyzer = SprintAnalyzer()
    dashboard = Dashboard()
    
    with st.spinner("Carregando dados da sprint..."):
        try:
            iteration_path = create_sprint_selector(azure_api)
            ids_with_estimates = azure_api.get_work_item_ids(iteration_path)
            if not ids_with_estimates:
                st.warning("⚠️ Nenhum Work Item encontrado na sprint selecionada.")
                return
            
            work_items = azure_api.get_work_items_details(ids_with_estimates)
            all_iterations = azure_api.get_all_iterations()
            selected_iteration = next(it for it in all_iterations if it["path"] == iteration_path)
            
            inicio_sprint = datetime.strptime(selected_iteration['attributes']['startDate'], '%Y-%m-%dT%H:%M:%SZ')
            fim_sprint = datetime.strptime(selected_iteration['attributes']['finishDate'], '%Y-%m-%dT%H:%M:%SZ')
            dias_uteis = analyzer.calcular_dias_uteis(inicio_sprint, fim_sprint)

            metricas_gerais = analyzer.calcular_metricas_gerais(work_items, inicio_sprint, fim_sprint)
            agrupados = analyzer.agrupar_por_dev(work_items, inicio_sprint, fim_sprint)

            st.subheader(f"🗓 Sprint Selecionada: `{iteration_path}`")
            st.write(f"Período: {inicio_sprint.strftime('%d/%m/%Y')} a {fim_sprint.strftime('%d/%m/%Y')}")
            st.write(f"Dias úteis: {dias_uteis} dias")

            dashboard.show_metrics(metricas_gerais)
            user_stories = azure_api.get_user_stories_with_task_hours(iteration_path)
            mostrar_card_userstories(user_stories)
            mostrar_card_tasks_done(work_items)
            mostrar_card_bugs(work_items)
            exibir_atividades_sustentacao(agrupados)
            mostrar_card_performance(work_items)

            # ✅ Aqui passa o parâmetro dias_uteis
            dashboard.show_dev_details(agrupados, dias_uteis)
            dashboard.show_comparison_chart(agrupados)
       

            st.markdown("## 📄 Exportar Relatório (HTML para PDF)")
            
            # ✅ Também usa dias_uteis aqui
            html_cards = gerar_html_cards(
                grouped_data=agrupados,
                sprint_title=iteration_path,
                periodo=f"{inicio_sprint.strftime('%d/%m/%Y')} a {fim_sprint.strftime('%d/%m/%Y')}",
                dias_uteis=dias_uteis
            )
            html_cards += gerar_html_userstories_card(user_stories)
            html_cards += gerar_html_tasks_done_card(work_items)
            html_cards += gerar_html_sustentacao_card(agrupados)
            html_cards += gerar_html_bugs_card(work_items)

            st.download_button(
                label="📥 Baixar HTML para salvar como PDF",
                data=html_cards,
                file_name=f"Relatorio_Sprint_{iteration_path.replace('\\', '_')}.html",
                mime="text/html"
            )
        except Exception as e:
            st.error(f"Erro ao buscar dados: {e}")
            return

if __name__ == "__main__":
    main()
