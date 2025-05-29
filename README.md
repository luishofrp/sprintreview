📊 Sprint Review Dashboard
Este projeto é um painel interativo desenvolvido com Python + Streamlit, que se conecta à API do Azure DevOps para extrair e analisar dados de sprints (itens, esforço, produtividade e performance por desenvolvedor).

✅ Funcionalidades
Seleção de sprint atual ou histórica

Cálculo de dias úteis com exclusão de feriados

Métricas gerais da sprint (itens, horas estimadas x realizadas, eficiência)

Detalhamento por desenvolvedor

Gráficos comparativos entre esforço estimado e realizado

🚀 Como rodar localmente
Clone o repositório:

bash
Copiar
Editar
git clone https://github.com/seu-usuario/seu-repositorio.git
cd seu-repositorio
Instale as dependências:

bash
Copiar
Editar
pip install -r requirements.txt
Crie um arquivo .env (opcional para testes locais) com sua variável:

env
Copiar
Editar
AZURE_PAT=seu_token_aqui
Execute o app:

bash
Copiar
Editar
streamlit run app.py

⚠️ Importante
Nunca exponha o token AZURE_PAT no código. Use os.getenv("AZURE_PAT") para capturar a variável com segurança.

Caso use este projeto em produção, considere proteger as informações exibidas no painel com autenticação.

👨‍💻 Desenvolvido por
Luis Henrique Oliveira Fachin
💼 Product Owner | 🧠 Inteligência de Negócios
📧 lusihof@gmail.com | 🌐 LinkedIn

📜 Licença
Este projeto está licenciado sob a MIT License – veja o arquivo LICENSE para detalhes.

