import pandas as pd
import streamlit as st
from datetime import datetime
from io import StringIO
import pdfkit
import os

config = pdfkit.configuration(wkhtmltopdf="C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe")

FERIADOS = ['01-01', '07-09', '25-12', '01-05', '25-01', '09-07', '19-03', '15-08']

# Valor fixo da hora para os desenvolvedores
VALOR_HORA = 26.78

st.set_page_config(layout="wide", page_title="Análise e Aprovação de Horas Extras")

st.title("⏱️ Gestão de Horas Extras")

menu = st.sidebar.radio("Menu", ["📊 Análise de Horas Extras", "✅ Aprovação e Geração de Relatório"])

uploaded_files = st.sidebar.file_uploader("📁 Envie arquivos CSV", type="csv", accept_multiple_files=True)

if uploaded_files:
    df_total = pd.concat([pd.read_csv(f) for f in uploaded_files], ignore_index=True)

    df_total['date'] = pd.to_datetime(df_total['date'])
    df_total['dia_semana'] = df_total['date'].dt.dayofweek
    df_total['feriado'] = df_total['date'].dt.strftime('%d-%m').isin(FERIADOS)
    df_total['fim_de_semana'] = df_total['dia_semana'] >= 5
    df_total['fora_horario_comercial'] = False
    df_total['hora_extra'] = df_total['feriado'] | df_total['fim_de_semana'] | df_total['fora_horario_comercial']
    df_total['horas'] = df_total['minutes'] / 60

    devs = df_total['user'].sort_values().unique()
    dev_selecionados = st.sidebar.multiselect("👤 Filtrar por desenvolvedor", devs, default=list(devs))

    df_filtrado = df_total[df_total['user'].isin(dev_selecionados)]

    if menu == "📊 Análise de Horas Extras":
        st.subheader("📊 Resumo de Horas Extras")
        resumo = df_filtrado[df_filtrado['hora_extra']].groupby('user')['horas'].sum().reset_index()
        resumo.columns = ['Colaborador', 'Horas Extras']
        st.dataframe(resumo.style.format({'Horas Extras': '{:.2f}'}), use_container_width=True)

        st.subheader("📋 Detalhamento das marcações com horas extras")
        df_extras = df_filtrado[df_filtrado['hora_extra']].copy()
        df_extras['Horas'] = df_extras['minutes'] / 60
        df_extras = df_extras[['user', 'date', 'title', 'type', 'Horas', 'feriado', 'fim_de_semana']]
        st.dataframe(df_extras, use_container_width=True)

    elif menu == "✅ Aprovação e Geração de Relatório":
        st.subheader("✅ Aprovação por Dev")
        for dev in df_filtrado['user'].unique():
            dev_data = df_filtrado[(df_filtrado['user'] == dev) & (df_filtrado['hora_extra'])]
            if dev_data.empty:
                continue

            st.markdown(f"### 👨‍💻 {dev}")
            aprovadas = []
            observacoes = []

            for idx, row in dev_data.iterrows():
                col1, col2 = st.columns([6, 1])
                with col1:
                    st.markdown(f"- 📅 {row['date'].date()} | **{row['title']}**")
                    obs = st.text_input(f"Observação ({idx})", key=f"obs_{dev}_{idx}")
                    observacoes.append((idx, obs))
                with col2:
                    aprovado = st.checkbox("Aprovar", key=f"chk_{dev}_{idx}")
                    if aprovado:
                        aprovadas.append(idx)

            total_horas_aprovadas = dev_data.loc[dev_data.index.isin(aprovadas), 'horas'].sum()
            valor_total = total_horas_aprovadas * VALOR_HORA

            st.markdown(f"💰 Valor da hora: R$ {VALOR_HORA:.2f}")
            st.markdown(f"⏱️ Total de horas extras aprovadas: **{total_horas_aprovadas:.2f}h**")
            st.markdown(f"💸 Valor total estimado: **R$ {valor_total:.2f}**")

            if st.button(f"📄 Gerar PDF de {dev}", key=f"btn_{dev}"):
                observacoes_dict = dict(observacoes)
                aprovadas_data = dev_data[dev_data.index.isin(aprovadas)]
                html = StringIO()
                html.write("""<html><head><meta charset="utf-8"><style>
                    body { font-family: Arial, sans-serif; margin: 40px; }
                    .card { border: 1px solid #ccc; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 2px 2px 10px #eee; }
                    .card h2, .card h3 { margin-top: 0; color: #2c3e50; }
                    .summary { background-color: #f4f6f8; }
                    table { width: 100%; border-collapse: collapse; margin-top: 10px; }
                    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                    th { background-color: #f0f0f0; }
                    .aprovado { color: green; font-weight: bold; }
                    .reprovado { color: red; font-weight: bold; }
                    .obs { font-style: italic; color: #555; margin-top: 5px; }
                </style></head><body>
                """)

                html.write(f"""
                    <div class='card'><h2>Relatório de Horas Extras - {dev}</h2></div>
                    <div class='card summary'>
                        <h3>🧮 Cálculo do Valor da Hora</h3>
                        <p><strong>Valor base mensal:</strong> R$ 4.500,00</p>
                        <p><strong>Quantidade de dias úteis base mês:</strong> 21 dias</p>
                        <p><strong>Horas por dia:</strong> 8 horas</p>
                        <p><strong>Fórmula:</strong> R$ 4.500 / (21 × 8) = <strong>R$ {VALOR_HORA:.2f} por hora</strong></p>
                    </div>
                    <div class='card summary'>
                        <h3>📊 Resumo das Horas Extras Aprovadas</h3>
                        <p><strong>Total de horas aprovadas:</strong> {total_horas_aprovadas:.2f}h</p>
                        <p><strong>Valor total estimado:</strong> R$ {valor_total:.2f}</p>
                    </div>
                    <div class='card'>
                        <h3>📋 Detalhamento das Atividades</h3>
                        <table><tr><th>Data</th><th>Atividade</th><th>Status</th></tr>
                """)

                for idx, row in dev_data.iterrows():
                    status = "✅ Aprovado" if idx in aprovadas else "❌ Não aprovado"
                    status_class = "aprovado" if idx in aprovadas else "reprovado"
                    html.write(f"<tr><td>{row['date'].date()}</td><td>{row['title']}</td><td class='{status_class}'>{status}</td></tr>")
                    if observacoes_dict.get(idx):
                        html.write(f"<tr><td colspan='3' class='obs'>Observação: {observacoes_dict[idx]}</td></tr>")

                html.write("</table></div></body></html>")

                # Gerar PDF
                pdf_filename = f"relatorio_{dev.replace(' ', '_').lower()}.pdf"
                pdfkit.from_string(html.getvalue(), pdf_filename, configuration=config)

                with open(pdf_filename, "rb") as pdf_file:
                    st.download_button(
                        label=f"⬇️ Baixar PDF de {dev}",
                        data=pdf_file.read(),
                        file_name=pdf_filename,
                        mime="application/pdf"
                    )

else:
    st.info("Envie um ou mais arquivos CSV no menu lateral para começar.")
