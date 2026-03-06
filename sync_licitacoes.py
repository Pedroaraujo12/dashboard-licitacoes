import urllib.request
import os
import json
import csv
import io
import urllib.parse
from datetime import datetime

# Configurações
SPREADSHEET_ID = "1YASjuPGJ40uirMIvoTzyGdlvehT3bJm66GuPgYjndWI"
TABLE_NAME = "licitacoes"

# Fallback values
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://qakrpkwmhlpynrphucfl.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "sb_publishable_GO7Aqg_eNO6hqUIl3rAzyg_GRuiIkWE")

# Mapeamento de colunas Planilha -> Supabase
# Mantendo o campo 'data_prevista' original que existe no banco
COLUMN_MAP = {
    "Data de Entrada": "data_entrada",
    "ID Processo": "id_processo",
    "Responsável": "responsavel",
    "Objeto Resumido": "objeto_resumido",
    "Demandante": "demandante",
    "Modalidade": "modalidade",
    "Prioridade": "prioridade",
    "Atividades Atual": "fase_atual",
    "Coordenação": "coordenacao",
    "Status": "status",
    "Data da Atividade": "data_prevista", 
    "Houve Recurso?": "houve_recurso",
    "Valor  Estimado (R$)": "vlr_estimado_anual",
    "Valor Homologado (R$)": "vlr_homologado",
    "Observações": "observacoes"
}

REQUIRED_COLUMNS = list(COLUMN_MAP.values()) + ["processo_link"]

def clean_currency(val):
    if not val: return 0.0
    clean = str(val).replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except:
        return 0.0

def parse_date(date_str):
    if not date_str or str(date_str).strip() == "" or date_str == "-": return None
    date_str = str(date_str).strip()
    formats = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except:
            continue
    return None

def get_sheets_data():
    maton_key = "0W3nESxcgh3yOr-bPH-2N__tX1T6wg_AcpMeEuv0xwyE1QrDLIEK9q8bqxJf8FDGg0LQ9rX4FRGuS0VSw-m6mPVU4sJRUOL_MrWtAlNQUg"
    print("Buscando dados e hiperlinks da planilha...")
    
    url_values = f"https://gateway.maton.ai/google-sheets/v4/spreadsheets/{SPREADSHEET_ID}/values/A1%3AZ1000?valueRenderOption=FORMATTED_VALUE"
    req_v = urllib.request.Request(url_values)
    req_v.add_header('Authorization', f'Bearer {maton_key}')
    
    url_meta = f"https://gateway.maton.ai/google-sheets/v4/spreadsheets/{SPREADSHEET_ID}?includeGridData=true&fields=sheets(data(rowData(values(hyperlink,textFormatRuns,effectiveValue))))"
    req_m = urllib.request.Request(url_meta)
    req_m.add_header('Authorization', f'Bearer {maton_key}')

    try:
        with urllib.request.urlopen(req_v) as res_v:
            data_json = json.load(res_v)
            values = data_json.get('values', [])
        
        links = {}
        rich_text = {}
        try:
            with urllib.request.urlopen(req_m) as res_m:
                meta = json.load(res_m)
                rows = meta['sheets'][0]['data'][0].get('rowData', [])
                
                obs_col_idx = -1
                id_proc_col_idx = -1
                if values:
                    for i, h in enumerate(values[0]):
                        if "Observações" in h: obs_col_idx = i
                        if "ID Processo" in h: id_proc_col_idx = i

                for i, row in enumerate(rows):
                    cell_vals = row.get('values', [])
                    # CAPTURA DO LINK REAL DA PLANILHA (na coluna ID Processo)
                    if id_proc_col_idx != -1 and len(cell_vals) > id_proc_col_idx:
                        link = cell_vals[id_proc_col_idx].get('hyperlink')
                        if link: links[i] = link
                    
                    if obs_col_idx != -1 and len(cell_vals) > obs_col_idx:
                        cell = cell_vals[obs_col_idx]
                        text = cell.get('effectiveValue', {}).get('stringValue', "")
                        runs = cell.get('textFormatRuns', [])
                        if runs and text:
                            html_text = ""
                            for r_idx, run in enumerate(runs):
                                start = run.get('startIndex', 0)
                                end = runs[r_idx+1].get('startIndex', len(text)) if r_idx+1 < len(runs) else len(text)
                                part = text[start:end]
                                fmt = run.get('format', {})
                                if fmt.get('bold'): part = f"<b>{part}</b>"
                                if fmt.get('italic'): part = f"<i>{part}</i>"
                                if fmt.get('underline'): part = f"<u>{part}</u>"
                                html_text += part
                            rich_text[i] = html_text
        except Exception as e:
            print(f"Aviso: Falha ao capturar links/metadados: {e}")

        return values, links, rich_text
    except Exception as e:
        print(f"Erro ao acessar Sheets: {e}")
        return None, None, None

def sync_to_supabase(rows, links, rich_text):
    if not rows: return "Erro: Sem dados."
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    sheet_headers = rows[0]
    data = []
    
    idx_dt_ativ = -1
    idx_dt_final = -1
    for i, h in enumerate(sheet_headers):
        if h == "Data da Atividade": idx_dt_ativ = i
        if h == "Data da Entrega": idx_dt_final = i

    for idx, row in enumerate(rows[1:], start=1):
        if not row or len(row) < 2: continue
        row_dict = {col: None for col in REQUIRED_COLUMNS}
        val_dt_ativ = ""
        val_dt_final = ""
        for i, header in enumerate(sheet_headers):
            if i < len(row):
                db_col = COLUMN_MAP.get(header)
                val = str(row[i]).strip()
                if i == idx_dt_ativ: val_dt_ativ = val
                if i == idx_dt_final: val_dt_final = val
                if db_col:
                    if db_col in ["vlr_estimado_anual", "vlr_homologado"]:
                        row_dict[db_col] = clean_currency(val)
                    elif db_col in ["data_entrada", "data_prevista"]:
                        row_dict[db_col] = parse_date(val)
                    elif db_col == "observacoes":
                        orig_obs = rich_text[idx] if idx in rich_text else val
                        meta_dates = f"<!--METADATA_DATES:ATIV={val_dt_ativ}|FINAL={val_dt_final}-->"
                        row_dict[db_col] = meta_dates + orig_obs
                    elif db_col in ["modalidade", "demandante", "fase_atual", "status", "coordenacao"]:
                        row_dict[db_col] = " ".join(val.split())
                    else:
                        row_dict[db_col] = val
        
        # ATRIBUIÇÃO DO LINK CAPTURADO
        row_dict["processo_link"] = links.get(idx, "")
        if row_dict.get("id_processo"):
            data.append(row_dict)
    
    if not data: return "Nenhum dado válido."
    print("Limpando dados antigos no Supabase...")
    url_del = f"{url}?id_processo=not.is.null"
    req_del = urllib.request.Request(url_del, method='DELETE')
    req_del.add_header('apikey', SUPABASE_KEY)
    req_del.add_header('Authorization', f'Bearer {SUPABASE_KEY}')
    try:
        with urllib.request.urlopen(req_del) as res_del:
            pass
    except:
        pass

    print(f"Sincronizando {len(data)} registros com links oficiais...")
    json_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=json_data, method='POST')
    req.add_header('apikey', SUPABASE_KEY)
    req.add_header('Authorization', f'Bearer {SUPABASE_KEY}')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Prefer', 'resolution=merge-duplicates')
    try:
        with urllib.request.urlopen(req) as res:
            return "Sincronização finalizada com sucesso."
    except Exception as e:
        return f"Erro Supabase: {e}"

if __name__ == "__main__":
    rows, links, rich_text = get_sheets_data()
    if rows:
        print(sync_to_supabase(rows, links, rich_text))
