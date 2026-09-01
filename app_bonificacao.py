import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "bonificacao_vendas.db"
PONTOS_POR_REAL = 1
REGRA_RESGATE = 1000

st.set_page_config(
    page_title="Sistema de Bonificacao de Vendas",
    page_icon="🎁",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown('''
<style>
    .main-header { font-size: 2.5rem; font-weight: 700; color: #1f4e79; text-align: center; margin-bottom: 0.5rem; }
    .sub-header { font-size: 1.1rem; color: #666; text-align: center; margin-bottom: 2rem; }
    .card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 15px; padding: 25px; color: white; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.15); }
    .card-green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .card-orange { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
    .card-blue { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
    .card h2 { margin: 0; font-size: 2.2rem; font-weight: 800; }
    .card p { margin: 5px 0 0 0; font-size: 1rem; opacity: 0.95; }
    .info-box { background-color: #e8f4fd; border-left: 5px solid #2196F3; padding: 15px 20px; border-radius: 8px; margin: 15px 0; }
    .success-box { background-color: #e8f5e9; border-left: 5px solid #4CAF50; padding: 15px 20px; border-radius: 8px; margin: 15px 0; }
</style>
''', unsafe_allow_html=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS vendas (id INTEGER PRIMARY KEY AUTOINCREMENT, data_upload TEXT, mes_referencia TEXT, cliente TEXT, cpf_cnpj TEXT, valor_venda REAL, pontos_gerados INTEGER, data_expiracao TEXT, status TEXT DEFAULT ativo)')
    cursor.execute('CREATE TABLE IF NOT EXISTS saldo_clientes (cliente TEXT PRIMARY KEY, cpf_cnpj TEXT, total_pontos INTEGER DEFAULT 0, pontos_expirados INTEGER DEFAULT 0, pontos_utilizados INTEGER DEFAULT 0, ultima_atualizacao TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS resgates (id INTEGER PRIMARY KEY AUTOINCREMENT, data_resgate TEXT, cliente TEXT, pontos_resgatados INTEGER, valor_resgate REAL, observacao TEXT)')
    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_PATH)

def calcular_pontos(valor_venda):
    return int(valor_venda * PONTOS_POR_REAL)

def calcular_valor_resgate(pontos):
    return (pontos / REGRA_RESGATE) * 10.0

def atualizar_saldos():
    conn = get_connection()
    cursor = conn.cursor()
    hoje = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("UPDATE vendas SET status = 'expirado' WHERE data_expiracao < ? AND status = 'ativo'", (hoje,))
    cursor.execute('DELETE FROM saldo_clientes')
    cursor.execute("SELECT cliente, cpf_cnpj, SUM(CASE WHEN status = 'ativo' THEN pontos_gerados ELSE 0 END) as pontos_ativos, SUM(CASE WHEN status = 'expirado' THEN pontos_gerados ELSE 0 END) as pontos_expirados FROM vendas GROUP BY cliente, cpf_cnpj")
    for row in cursor.fetchall():
        cliente, cpf, ativos, expirados = row
        ativos = ativos or 0
        expirados = expirados or 0
        cursor.execute('SELECT COALESCE(SUM(pontos_resgatados), 0) FROM resgates WHERE cliente = ?', (cliente,))
        utilizados = cursor.fetchone()[0] or 0
        saldo_final = max(0, ativos - utilizados)
        cursor.execute('INSERT OR REPLACE INTO saldo_clientes (cliente, cpf_cnpj, total_pontos, pontos_expirados, pontos_utilizados, ultima_atualizacao) VALUES (?, ?, ?, ?, ?, ?)', (cliente, cpf or '', saldo_final, expirados, utilizados, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def processar_csv(df, mes_referencia):
    conn = get_connection()
    cursor = conn.cursor()
    data_upload = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data_expiracao = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
    registros_inseridos = 0
    for _, row in df.iterrows():
        cliente = str(row.get('cliente', row.get('CLIENTE', row.get('Client', row.iloc[0])))).strip()
        cpf_cnpj = ''
        for col in df.columns:
            if any(k in col.upper() for k in ['CPF', 'CNPJ', 'DOCUMENTO', 'DOC']):
                cpf_cnpj = str(row.get(col, '')).strip()
                break
        valor = 0
        for col in df.columns:
            if any(k in col.upper() for k in ['VALOR', 'TOTAL', 'VALOR_VENDA', 'VALOR TOTAL', 'PRECO']):
                try:
                    v = str(row.get(col, '0')).replace('R$', '').replace('.', '').replace(',', '.').strip()
                    valor = float(v)
                    break
                except:
                    continue
        if valor <= 0:
            continue
        pontos = calcular_pontos(valor)
        cursor.execute("INSERT INTO vendas (data_upload, mes_referencia, cliente, cpf_cnpj, valor_venda, pontos_gerados, data_expiracao, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'ativo')", (data_upload, mes_referencia, cliente, cpf_cnpj, valor, pontos, data_expiracao))
        registros_inseridos += 1
    conn.commit()
    conn.close()
    atualizar_saldos()
    return registros_inseridos

def resgatar_pontos(cliente, pontos, observacao=''):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT total_pontos FROM saldo_clientes WHERE cliente = ?', (cliente,))
    result = cursor.fetchone()
    if not result or result[0] < pontos:
        conn.close()
        return False, 'Saldo insuficiente!'
    valor = calcular_valor_resgate(pontos)
    data_resgate = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('INSERT INTO resgates (data_resgate, cliente, pontos_resgatados, valor_resgate, observacao) VALUES (?, ?, ?, ?, ?)', (data_resgate, cliente, pontos, valor, observacao))
    conn.commit()
    conn.close()
    atualizar_saldos()
    return True, f'Resgate de R$ {valor:.2f} realizado com sucesso!'

def render_header():
    st.markdown('<div class="main-header">🎁 Sistema de Bonificacao de Vendas</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Transforme vendas em pontos e pontos em recompensas</div>', unsafe_allow_html=True)

def render_dashboard():
    conn = get_connection()
    col1, col2, col3, col4 = st.columns(4)
    total_clientes = pd.read_sql("SELECT COUNT(*) FROM saldo_clientes WHERE total_pontos > 0", conn).iloc[0, 0]
    total_pontos = pd.read_sql("SELECT COALESCE(SUM(total_pontos), 0) FROM saldo_clientes", conn).iloc[0, 0]
    total_vendas = pd.read_sql("SELECT COALESCE(SUM(valor_venda), 0) FROM vendas", conn).iloc[0, 0]
    total_resgatado = pd.read_sql("SELECT COALESCE(SUM(valor_resgate), 0) FROM resgates", conn).iloc[0, 0]
    with col1:
        st.markdown(f'<div class="card card-green"><h2>{total_clientes}</h2><p>Clientes Ativos</p></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="card"><h2>{total_pontos:,}</h2><p>Pontos em Circulacao</p></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="card card-orange"><h2>R$ {total_vendas:,.2f}</h2><p>Total em Vendas</p></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="card card-blue"><h2>R$ {total_resgatado:,.2f}</h2><p>Total Resgatado</p></div>', unsafe_allow_html=True)
    st.markdown('<br>', unsafe_allow_html=True)
    df_saldos = pd.read_sql("SELECT cliente as 'Cliente', cpf_cnpj as 'CPF/CNPJ', total_pontos as 'Pontos Disponiveis', pontos_expirados as 'Pontos Expirados', pontos_utilizados as 'Pontos Utilizados', ROUND(total_pontos / 1000.0 * 10, 2) as 'Valor Disponivel (R$)', ultima_atualizacao as 'Ultima Atualizacao' FROM saldo_clientes WHERE total_pontos > 0 OR pontos_expirados > 0 OR pontos_utilizados > 0 ORDER BY total_pontos DESC", conn)
    conn.close()
    st.subheader('📋 Relacao de Clientes e Pontos')
    if not df_saldos.empty:
        st.dataframe(df_saldos, use_container_width=True, hide_index=True)
    else:
        st.info('Nenhum cliente cadastrado ainda. Faca o upload do CSV de vendas.')

def render_upload():
    st.subheader('📤 Upload de Vendas (CSV)')
    st.markdown('<div class="info-box"><b>📌 Formato esperado do CSV:</b><br>O arquivo deve conter pelo menos as colunas: <b>cliente</b> e <b>valor</b> (ou variacoes como "valor_venda", "total", "preco").<br>Colunas opcionais: <b>cpf</b>, <b>cnpj</b>, <b>documento</b>.<br><b>Regra:</b> R$ 1,00 = 1 ponto | 1000 pontos = R$ 10,00 | Validade: 1 ano</div>', unsafe_allow_html=True)
    mes = st.selectbox('Mes de referencia:', ['Janeiro', 'Fevereiro', 'Marco', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'], index=datetime.now().month - 1)
    ano = st.number_input('Ano:', min_value=2020, max_value=2030, value=datetime.now().year)
    mes_ref = f'{mes} {ano}'
    uploaded_file = st.file_uploader('Escolha o arquivo CSV', type=['csv'])
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file, encoding='utf-8')
            if df.empty:
                st.error('O arquivo CSV esta vazio!')
                return
            st.success(f'Arquivo carregado! {len(df)} registros encontrados.')
            st.write('Pre-visualizacao:')
            st.dataframe(df.head(10), use_container_width=True)
            st.markdown(f'<div class="success-box"><b>✅ Resumo do processamento:</b><br>• Mes de referencia: {mes_ref}<br>• Total de registros: {len(df)}<br>• Validade dos pontos: 1 ano a partir de hoje</div>', unsafe_allow_html=True)
            if st.button('🚀 Processar Vendas', type='primary', use_container_width=True):
                with st.spinner('Processando...'):
                    registros = processar_csv(df, mes_ref)
                st.success(f'✅ {registros} vendas processadas com sucesso!')
                st.balloons()
                st.rerun()
        except Exception as e:
            st.error(f'Erro ao processar o arquivo: {e}')

def render_resgate():
    st.subheader('💰 Resgate de Pontos')
    conn = get_connection()
    df_clientes = pd.read_sql("SELECT cliente, total_pontos, ROUND(total_pontos / 1000.0 * 10, 2) as valor_disponivel FROM saldo_clientes WHERE total_pontos > 0 ORDER BY total_pontos DESC", conn)
    conn.close()
    if df_clientes.empty:
        st.info('Nenhum cliente com saldo disponivel para resgate.')
        return
    cliente_selecionado = st.selectbox('Selecione o cliente:', df_clientes['cliente'].tolist(), format_func=lambda x: f"{x} -- {df_clientes[df_clientes['cliente']==x]['total_pontos'].values[0]} pts (R$ {df_clientes[df_clientes['cliente']==x]['valor_disponivel'].values[0]:.2f})")
    if cliente_selecionado:
        saldo = df_clientes[df_clientes['cliente']==cliente_selecionado]['total_pontos'].values[0]
        valor_disp = df_clientes[df_clientes['cliente']==cliente_selecionado]['valor_disponivel'].values[0]
        col1, col2 = st.columns(2)
        with col1:
            st.metric('Saldo em Pontos', f'{saldo:,}')
        with col2:
            st.metric('Valor Disponivel', f'R$ {valor_disp:,.2f}')
        st.markdown(f'<div class="info-box"><b>💡 Regra de resgate:</b> A cada <b>1.000 pontos</b> voce resgata <b>R$ 10,00</b>.<br>Seu saldo permite resgatar ate <b>R$ {valor_disp:,.2f}</b>.</div>', unsafe_allow_html=True)
        pontos_input = st.number_input('Quantidade de pontos para resgatar:', min_value=100, max_value=int(saldo), step=100, value=min(1000, int(saldo)))
        valor_resgate = calcular_valor_resgate(pontos_input)
        st.info(f'💵 Valor do resgate: **R$ {valor_resgate:,.2f}**')
        observacao = st.text_input('Observacao (opcional):', placeholder='Ex: Troca por produto X')
        if st.button('✅ Confirmar Resgate', type='primary', use_container_width=True):
            sucesso, msg = resgatar_pontos(cliente_selecionado, pontos_input, observacao)
            if sucesso:
                st.success(msg)
                st.balloons()
                st.rerun()
            else:
                st.error(msg)

def render_historico():
    st.subheader('📜 Historico Completo')
    tab1, tab2, tab3 = st.tabs(['📊 Vendas', '💰 Resgates', '⏰ Pontos a Expirar'])
    conn = get_connection()
    with tab1:
        df_vendas = pd.read_sql("SELECT mes_referencia as 'Mes', cliente as 'Cliente', cpf_cnpj as 'CPF/CNPJ', valor_venda as 'Valor (R$)', pontos_gerados as 'Pontos Gerados', data_expiracao as 'Data de Expiracao', status as 'Status' FROM vendas ORDER BY data_upload DESC", conn)
        if not df_vendas.empty:
            st.dataframe(df_vendas, use_container_width=True, hide_index=True)
            csv = df_vendas.to_csv(index=False).encode('utf-8')
            st.download_button('📥 Baixar CSV de Vendas', csv, 'historico_vendas.csv', 'text/csv')
        else:
            st.info('Nenhuma venda registrada.')
    with tab2:
        df_resgates = pd.read_sql("SELECT data_resgate as 'Data', cliente as 'Cliente', pontos_resgatados as 'Pontos', valor_resgate as 'Valor (R$)', observacao as 'Observacao' FROM resgates ORDER BY data_resgate DESC", conn)
        if not df_resgates.empty:
            st.dataframe(df_resgates, use_container_width=True, hide_index=True)
            csv = df_resgates.to_csv(index=False).encode('utf-8')
            st.download_button('📥 Baixar CSV de Resgates', csv, 'historico_resgates.csv', 'text/csv')
        else:
            st.info('Nenhum resgate realizado.')
    with tab3:
        hoje = datetime.now().strftime('%Y-%m-%d')
        daqui_30_dias = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        df_expirando = pd.read_sql("SELECT cliente as 'Cliente', mes_referencia as 'Mes da Venda', pontos_gerados as 'Pontos', data_expiracao as 'Data de Expiracao', ROUND(pontos_gerados / 1000.0 * 10, 2) as 'Valor (R$)' FROM vendas WHERE status = 'ativo' AND data_expiracao BETWEEN ? AND ? ORDER BY data_expiracao", conn, params=(hoje, daqui_30_dias))
        if not df_expirando.empty:
            st.warning(f'⚠️ {len(df_expirando)} registros de pontos irao expirar nos proximos 30 dias!')
            st.dataframe(df_expirando, use_container_width=True, hide_index=True)
        else:
            st.success('✅ Nenhum ponto ira expirar nos proximos 30 dias.')
    conn.close()

def render_relatorios():
    st.subheader('📈 Relatorios e Analises')
    conn = get_connection()
    df_mes = pd.read_sql("SELECT mes_referencia as mes, SUM(valor_venda) as total, SUM(pontos_gerados) as pontos FROM vendas GROUP BY mes_referencia ORDER BY data_upload", conn)
    if not df_mes.empty:
        col1, col2 = st.columns(2)
        with col1:
            st.bar_chart(df_mes.set_index('mes')['total'], use_container_width=True)
            st.caption('💵 Total de Vendas por Mes')
        with col2:
            st.bar_chart(df_mes.set_index('mes')['pontos'], use_container_width=True)
            st.caption('🎁 Total de Pontos Gerados por Mes')
    df_top = pd.read_sql("SELECT cliente, total_pontos, ROUND(total_pontos / 1000.0 * 10, 2) as valor FROM saldo_clientes WHERE total_pontos > 0 ORDER BY total_pontos DESC LIMIT 10", conn)
    if not df_top.empty:
        st.subheader('🏆 Top 10 Clientes')
        st.bar_chart(df_top.set_index('cliente')['total_pontos'], use_container_width=True)
    conn.close()

def main():
    init_db()
    render_header()
    menu = st.sidebar.radio('📌 Menu', ['🏠 Dashboard', '📤 Upload de Vendas', '💰 Resgate de Pontos', '📜 Historico', '📈 Relatorios'], index=0)
    st.sidebar.markdown('---')
    st.sidebar.markdown("<div style='font-size: 0.85rem; color: #666;'><b>Regras do Programa:</b><br>• R$ 1,00 = 1 ponto<br>• 1.000 pts = R$ 10,00<br>• Validade: 1 ano<br>• Resgate minimo: 100 pts</div>", unsafe_allow_html=True)
    if menu == '🏠 Dashboard':
        render_dashboard()
    elif menu == '📤 Upload de Vendas':
        render_upload()
    elif menu == '💰 Resgate de Pontos':
        render_resgate()
    elif menu == '📜 Historico':
        render_historico()
    elif menu == '📈 Relatorios':
        render_relatorios()

if __name__ == '__main__':
    main()