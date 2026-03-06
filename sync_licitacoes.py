import urllib.request
import os
import json
from datetime import datetime

SPREADSHEET_ID = "1YASjuPGJ40uirMIvoTzyGdlvehT3bJm66GuPgYjndWI"
TABLE_NAME = "licitacoes"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://qakrpkwmhlpynrphucfl.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "sb_publishable_GO7Aqg_eNO6hqUIl3rAzyg_GRuiIkWE")

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

def clean_currency_final(val):
    if not val: return 0.0
    # Limpeza radical: remove tudo que não é número, vírgula ou ponto
    s = "".join(c for c in str(val) if c.isdigit() or c in ",.")
    if not s: return 0.0
    
    # Lógica para formato brasileiro (1.234,56)
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    
    try:
        return float(s)
    except:
        return 0.0

def parse_date(date_str):
    if not date_str or str(date_str).strip() in ["", "-", "None"]: return None
    formats = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
    for fmt in formats:
        try: return datetime.strptime(str(date_str).strip(), fmt).strftime("%Y-%m-%d")
        except: continue
    return None

def get_sheets_data():
    maton_key = "0W3nESxcgh3yOr-bPH-2N__tX1T6wg_AcpMeEuv0xwyE1QrDLIEK9q8bqxJf8FDGg0LQ9rX4FRGuS0VSw-m6mPVU4sJRUOL_MrWtAlNQUg"
    url_v = f"https://gateway.maton.ai/google-sheets/v4/spreadsheets/{SPREADSHEET_ID}/values/A1%3AZ1000?valueRenderOption=FORMATTED_VALUE"
    url_f = f"https://gateway.maton.ai/google-sheets/v4/spreadsheets/{SPREADSHEET_ID}/values/Fases!C:C"
    url_m = f"https://gateway.maton.ai/google-sheets/v4/spreadsheets/{SPREADSHEET_ID}?includeGridData=true&fields=sheets(data(rowData(values(hyperlink,textFormatRuns,effectiveValue))))"
    
    try:
        req_v = urllib.request.Request(url_v); req_v.add_header('Authorization', f'Bearer {maton_key}')
        with urllib.request.urlopen(req_v) as res: values = json.load(res).get('values', [])
        
        req_f = urllib.request.Request(url_f); req_f.add_header('Authorization', f'Bearer {maton_key}')
        with urllib.request.urlopen(req_f) as res: 
            f_data = json.load(res).get('values', [])
            lista_fases = [r[0] for r in f_data if r and r[0].strip() and r[0] != "Descrição"]

        req_m = urllib.request.Request(url_m); req_m.add_header('Authorization', f'Bearer {maton_key}')
        with urllib.request.urlopen(req_m) as res:
            meta = json.load(res)
            rows_meta = meta['sheets'][0]['data'][0].get('rowData', [])
            id_idx, obs_idx, links, rich = -1, -1, {}, {}
            if values:
                for i, h in enumerate(values[0]):
                    if "ID Processo" in h: id_idx = i
                    if "Observações" in h: obs_idx = i
            for i, row in enumerate(rows_meta):
                cv = row.get('values', [])
                if id_idx != -1 and len(cv) > id_idx:
                    lk = cv[id_idx].get('hyperlink')
                    if lk: links[i] = lk
                if obs_idx != -1 and len(cv) > obs_idx:
                    cell = cv[obs_idx]
                    txt = cell.get('effectiveValue', {}).get('stringValue', "")
                    runs = cell.get('textFormatRuns', [])
                    if runs and txt:
                        ht = ""
                        for r_i, run in enumerate(runs):
                            start = run.get('startIndex', 0)
                            end = runs[r_i+1].get('startIndex', len(txt)) if r_i+1 < len(runs) else len(txt)
                            part = txt[start:end]
                            fmt = run.get('format', {})
                            if fmt.get('bold'): part = f"<b>{part}</b>"
                            if fmt.get('italic'): part = f"<i>{part}</i>"
                            if fmt.get('underline'): part = f"<u>{part}</u>"
                            ht += part
                        rich[i] = ht
        return values, links, rich, lista_fases
    except Exception as e:
        print(f"Erro: {e}")
        return None, None, None, None

def sync_to_supabase(rows, links, rich_text, lista_fases):
    if not rows: return "Erro."
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = rows[0]
    data = []
    fases_pipe = "|".join(lista_fases)
    idx_ativ, idx_final = -1, -1
    for i, h in enumerate(headers):
        if h == "Data da Atividade": idx_ativ = i
        if h == "Data da Entrega": idx_final = i

    for idx, row in enumerate(rows[1:], start=1):
        if not row or len(row) < 2: continue
        row_dict = {col: None for col in REQUIRED_COLUMNS}
        v_ativ, v_final = "", ""
        for i, header in enumerate(headers):
            if i < len(row):
                db_col = COLUMN_MAP.get(header)
                val = str(row[i]).strip()
                if i == idx_ativ: v_ativ = val
                if i == idx_final: v_final = val
                if db_col:
                    if db_col in ["vlr_estimado_anual", "vlr_homologado"]:
                        # AQUI ESTAVA O ERRO: Convertendo para float e salvando como texto no JSON
                        row_dict[db_col] = str(clean_currency_final(val))
                    elif db_col in ["data_entrada", "data_prevista"]:
                        row_dict[db_col] = parse_date(val)
                    elif db_col == "observacoes":
                        orig = rich_text[idx] if idx in rich_text else val
                        cat = f"<!--CATALOGO_FASES:{fases_pipe}-->" if idx == 1 else ""
                        row_dict[db_col] = f"<!--METADATA_DATES:ATIV={v_ativ}|FINAL={v_final}-->{cat}{orig}"
                    elif db_col in ["modalidade", "demandante", "fase_atual", "status", "coordenacao"]:
                        row_dict[db_col] = " ".join(val.split())
                    else:
                        row_dict[db_col] = val
        row_dict["processo_link"] = links.get(idx, "")
        if row_dict.get("id_processo"): data.append(row_dict)

    req_del = urllib.request.Request(f"{url}?id_processo=not.is.null", method='DELETE')
    req_del.add_header('apikey', SUPABASE_KEY); req_del.add_header('Authorization', f'Bearer {SUPABASE_KEY}')
    try: urllib.request.urlopen(req_del)
    except: pass

    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), method='POST')
    req.add_header('apikey', SUPABASE_KEY); req.add_header('Authorization', f'Bearer {SUPABASE_KEY}')
    req.add_header('Content-Type', 'application/json'); req.add_header('Prefer', 'resolution=merge-duplicates')
    try:
        with urllib.request.urlopen(req) as res: return "Sucesso."
    except Exception as e: return str(e)

if __name__ == "__main__":
    r, l, rt, lf = get_sheets_data()
    if r: print(sync_to_supabase(r, l, rt, lf))
