"""
pipeline.py
-----------
Pipeline de Data Science para consolidação de transações financeiras e
cotações da Fintech, com limpeza, engenharia de dados, detecção de
anomalias (Z-Score) e geração de relatório visual.

Uso:
    python generate_data.py   # gera transacoes.csv e cotacoes.csv
    python pipeline.py        # executa o pipeline e gera outputs/

Saídas (pasta outputs/):
    - transacoes_limpas.csv
    - pivot_risco_mes.csv
    - anomalias_zscore.csv
    - transacoes_suspeitas_setembro.csv
    - grafico_transacoes_diarias.png
"""
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

pd.set_option('display.width', 120)

INPUT_TRANSACOES = 'transacoes.csv'
INPUT_COTACOES = 'cotacoes.csv'
OUTPUT_DIR = 'outputs'

os.makedirs(OUTPUT_DIR, exist_ok=True)


def carregar_cotacoes(path_csv: str) -> pd.DataFrame:
    """Carrega e limpa o arquivo de cotações (UTF-8), usado para consolidar
    o relatório diário de transações com a cotação da empresa no dia."""
    df_cot = pd.read_csv(path_csv, encoding='utf-8', parse_dates=['data'])
    # interpolação temporal para preencher cotações ausentes (NaN)
    df_cot = df_cot.sort_values('data')
    df_cot['cotacao_usd'] = df_cot['cotacao_usd'].interpolate(method='linear')
    return df_cot


def secao(titulo: str) -> None:
    print('\n' + '=' * 70)
    print(titulo)
    print('=' * 70)


# ---------------------------------------------------------------------------
# 1. INGESTÃO, PERFORMANCE E LIMPEZA
# ---------------------------------------------------------------------------
def carregar_e_limpar(path_csv: str) -> pd.DataFrame:
    secao('1. INGESTÃO E LIMPEZA')

    # Encoding legado -> latin1, sem corromper acentuação
    df = pd.read_csv(path_csv, encoding='latin1')
    print(f"Registros brutos carregados: {len(df)}")
    print(f"Valores ausentes em 'valor' antes da imputação: {df['valor'].isna().sum()}")

    # Imputação da mediana por estado (vetorizado via groupby+transform)
    df['valor'] = df['valor'].fillna(
        df.groupby('estado_cliente')['valor'].transform('median')
    )
    print(f"Valores ausentes em 'valor' após imputação: {df['valor'].isna().sum()}")

    # Coluna estática de rastreabilidade do pipeline
    df['plataforma'] = 'Mobile'

    return df


# ---------------------------------------------------------------------------
# 2. ENGENHARIA DE DADOS & ALINHAMENTO TEMPORAL
# ---------------------------------------------------------------------------
def transformar_temporal(df: pd.DataFrame) -> pd.DataFrame:
    secao('2. ENGENHARIA DE DADOS & ALINHAMENTO TEMPORAL')

    df['data_transacao'] = pd.to_datetime(df['data_transacao'])
    # tz_localize exige que a série ainda esteja "naive" (sem timezone)
    if df['data_transacao'].dt.tz is None:
        df['data_transacao'] = df['data_transacao'].dt.tz_localize('America/Sao_Paulo')

    df['dia_semana'] = df['data_transacao'].dt.day_name()
    df['mes'] = df['data_transacao'].dt.month_name()

    duplicadas = df.duplicated().sum()
    df = df.drop_duplicates(keep='first')
    print(f"Transações duplicadas removidas: {duplicadas}")
    print(f"Total de registros após deduplicação: {len(df)}")

    return df


# ---------------------------------------------------------------------------
# 3. OPERAÇÕES VETORIZADAS E FILTROS BITWISE
# ---------------------------------------------------------------------------
def filtrar_suspeitas_setembro(df: pd.DataFrame) -> pd.DataFrame:
    secao('3. FILTRO VETORIZADO (BITWISE) - SETEMBRO / SP-RJ / VALOR > 5000')

    filtro = (
        (df['data_transacao'].dt.month == 9)
        & ((df['estado_cliente'] == 'SP') | (df['estado_cliente'] == 'RJ'))
        & (df['valor'] > 5000.00)
    )
    df_suspeitas = df.loc[filtro].copy()
    print(f"Transações que atendem aos critérios: {len(df_suspeitas)}")

    return df_suspeitas


# ---------------------------------------------------------------------------
# 4. CRUZAMENTO DE DADOS & AGREGAÇÃO
# ---------------------------------------------------------------------------
def aplicar_risco_e_pivot(df: pd.DataFrame) -> pd.DataFrame:
    secao('4. CRUZAMENTO DE DADOS (map) & PIVOT TABLE')

    risco_dict = {
        'C100': 'Baixo',
        'C101': 'Alto',
        'C102': 'Medio',
        'C103': 'Baixo',
        'C104': 'Alto',
    }
    df['nivel_risco'] = df['id_cliente'].map(risco_dict)

    pivot = pd.pivot_table(
        df,
        index='mes',
        columns='nivel_risco',
        values='valor',
        aggfunc='sum',
        margins=True,
        margins_name='Total',
    ).round(2)

    print(pivot)
    return pivot


# ---------------------------------------------------------------------------
# 5. DETECÇÃO ESTATÍSTICA DE OUTLIERS (Z-SCORE)
# ---------------------------------------------------------------------------
def detectar_anomalias(df: pd.DataFrame, limite_z: float = 2.5) -> pd.DataFrame:
    secao('5. DETECÇÃO DE ANOMALIAS (Z-SCORE POR ESTADO)')

    # Z-score vetorizado por estado, sem laços for
    grupo = df.groupby('estado_cliente')['valor']
    media = grupo.transform('mean')
    desvio = grupo.transform('std')
    df['zscore_estado'] = (df['valor'] - media) / desvio

    df_anomalias = df.loc[df['zscore_estado'] > limite_z].copy()
    df_anomalias = df_anomalias.sort_values('zscore_estado', ascending=False)

    print(f"Transações classificadas como potenciais anomalias (Z > {limite_z}): {len(df_anomalias)}")
    if not df_anomalias.empty:
        cols = ['id_cliente', 'estado_cliente', 'valor', 'zscore_estado']
        print(df_anomalias[cols].head(10).to_string(index=False))

    return df_anomalias


# ---------------------------------------------------------------------------
# 6. VISUALIZAÇÃO GRÁFICA ORIENTADA A OBJETOS (MATPLOTLIB)
# ---------------------------------------------------------------------------
def gerar_grafico_diario(df: pd.DataFrame, path_saida: str) -> None:
    secao('6. GERAÇÃO DO GRÁFICO (VALOR DIÁRIO x MÉDIA MÓVEL 7 DIAS)')

    serie_diaria = (
        df.set_index('data_transacao')['valor']
        .resample('D')
        .sum()
        .sort_index()
    )
    media_movel = serie_diaria.rolling(7).mean()

    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(serie_diaria.index, serie_diaria.values,
            label='Valor total de transações diárias',
            color='#4C72B0', linewidth=1.5, alpha=0.8)
    ax.plot(media_movel.index, media_movel.values,
            label='Média móvel (7 dias)',
            color='#C44E52', linewidth=2.5)

    ax.set_ylim(bottom=0)
    ax.set_title('Volume Diário de Transações vs. Média Móvel de 7 Dias', fontsize=14, fontweight='bold')
    ax.set_xlabel('Data')
    ax.set_ylabel('Valor total (R$)')
    ax.legend(loc='upper left')
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()

    fig.savefig(path_saida, dpi=150)
    plt.close(fig)
    print(f"Gráfico salvo em: {path_saida}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if not os.path.exists(INPUT_TRANSACOES):
        raise FileNotFoundError(
            f"'{INPUT_TRANSACOES}' não encontrado. Execute antes: python generate_data.py"
        )

    df = carregar_e_limpar(INPUT_TRANSACOES)
    df = transformar_temporal(df)

    df_suspeitas = filtrar_suspeitas_setembro(df)
    pivot = aplicar_risco_e_pivot(df)
    df_anomalias = detectar_anomalias(df)

    gerar_grafico_diario(df, os.path.join(OUTPUT_DIR, 'grafico_transacoes_diarias.png'))

    # Consolidação com o segundo arquivo de log (cotações da empresa)
    df_consolidado = None
    if os.path.exists(INPUT_COTACOES):
        secao('EXTRA: CONSOLIDAÇÃO COM COTAÇÕES DIÁRIAS')
        df_cot = carregar_cotacoes(INPUT_COTACOES)
        resumo_diario = (
            df.set_index('data_transacao')['valor']
            .resample('D').sum()
            .rename('valor_total_transacoes')
            .reset_index()
        )
        resumo_diario['data'] = resumo_diario['data_transacao'].dt.tz_localize(None)
        df_consolidado = resumo_diario.merge(df_cot, on='data', how='left')
        df_consolidado['valor_total_usd'] = (
            df_consolidado['valor_total_transacoes'] / df_consolidado['cotacao_usd']
        ).round(2)
        df_consolidado = df_consolidado.drop(columns=['data_transacao'])
        print(df_consolidado.head())
        df_consolidado.to_csv(os.path.join(OUTPUT_DIR, 'consolidado_diario_cotacao.csv'), index=False)

    # Persistência dos artefatos do pipeline
    df.to_csv(os.path.join(OUTPUT_DIR, 'transacoes_limpas.csv'), index=False)
    pivot.to_csv(os.path.join(OUTPUT_DIR, 'pivot_risco_mes.csv'))
    df_anomalias.to_csv(os.path.join(OUTPUT_DIR, 'anomalias_zscore.csv'), index=False)
    df_suspeitas.to_csv(os.path.join(OUTPUT_DIR, 'transacoes_suspeitas_setembro.csv'), index=False)

    secao('RESUMO FINAL')
    print(f"Total de transações processadas : {len(df)}")
    print(f"Transações suspeitas (set/SP-RJ/>5000) : {len(df_suspeitas)}")
    print(f"Anomalias detectadas (Z > 2.5)   : {len(df_anomalias)}")
    print(f"Arquivos gerados em '{OUTPUT_DIR}/':")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        print(f"  - {f}")


if __name__ == '__main__':
    main()
