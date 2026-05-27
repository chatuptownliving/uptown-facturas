#!/usr/bin/env python3
"""Uptown Living — Servidor completo con 9 documentos"""

from flask import Flask, request, jsonify, send_from_directory, redirect
import os, re, zipfile, shutil, tempfile, json, requests
from pathlib import Path
import anthropic

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'uptown-secret-2026')

BASE_DIR = Path(__file__).parent / 'docs'
DOCS_BASE = {
    'contrato':   BASE_DIR / 'Contrato_603-_Juan_Carlos_Cordoba_Manzanares.docx',
    'apartado':   BASE_DIR / '2_-APARTADO_NUEVO.docx',
    'acta':       BASE_DIR / '3_-ACTA_DE_ENTREGA_Y_RECEPCION_102.docx',
    'poliza':     BASE_DIR / '4_-POLIZA_DE_GARANTIA_102.docx',
    'responsiva': BASE_DIR / '5-RESPONSIVA_DE_MUDANZA_102.docx',
    'reporte':    BASE_DIR / '6_-REPORTE_DE_REPARACION_102.docx',
    'aviso':      BASE_DIR / '7_-AVISO_MANTENIMIENTO.docx',
    'cfe':        BASE_DIR / 'REQUISITOS_CONTRATACION_CFE_2026.docx',
    'bienvenida': BASE_DIR / '9_-BIENVENIDA.docx',
}

CONTRATOS_FOLDER_ID = '194DT0gPMKvmpW-_g6mBcDxu4SUCI5YSH'
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
REDIRECT_URI = 'https://uptown-contratos-production.up.railway.app/oauth/callback'
drive_tokens = {}

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/oauth/login')
def oauth_login():
    url = (f"https://accounts.google.com/o/oauth2/v2/auth"
           f"?client_id={GOOGLE_CLIENT_ID}&redirect_uri={REDIRECT_URI}"
           f"&response_type=code&scope=https://www.googleapis.com/auth/drive"
           f"&access_type=offline&prompt=consent")
    return redirect(url)

@app.route('/oauth/callback')
def oauth_callback():
    code = request.args.get('code')
    if not code:
        return "Error", 400
    resp = requests.post('https://oauth2.googleapis.com/token', data={
        'code': code, 'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI, 'grant_type': 'authorization_code'
    })
    tokens = resp.json()
    if 'access_token' in tokens:
        drive_tokens['access_token'] = tokens['access_token']
        drive_tokens['refresh_token'] = tokens.get('refresh_token', '')
        return '''<html><body style="font-family:sans-serif;text-align:center;padding:50px;background:#1e1e1e;color:#efefef">
        <h2 style="color:#E18F00">✓ Google Drive autorizado correctamente</h2>
        <p>Ya puedes cerrar esta ventana.</p>
        <script>setTimeout(()=>window.close(),3000)</script></body></html>'''
    return f"Error: {tokens}", 400

def get_drive_token():
    if not drive_tokens.get('access_token'):
        return None
    if drive_tokens.get('refresh_token'):
        try:
            resp = requests.post('https://oauth2.googleapis.com/token', data={
                'refresh_token': drive_tokens['refresh_token'],
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'grant_type': 'refresh_token'
            })
            t = resp.json()
            if 'access_token' in t:
                drive_tokens['access_token'] = t['access_token']
        except:
            pass
    return drive_tokens.get('access_token')

def crear_carpeta_drive(nombre, parent_id, token):
    h = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    b = {'name': nombre, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    r = requests.post('https://www.googleapis.com/drive/v3/files', headers=h, json=b)
    return r.json().get('id')

def subir_archivo_drive(filepath, folder_id, token):
    mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    boundary = 'uptown_bnd'
    with open(filepath, 'rb') as f:
        content = f.read()
    meta = json.dumps({'name': os.path.basename(filepath), 'parents': [folder_id]}).encode()
    body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
            + meta + f'\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode()
            + content + f'\r\n--{boundary}--'.encode())
    h = {'Authorization': f'Bearer {token}', 'Content-Type': f'multipart/related; boundary={boundary}'}
    r = requests.post('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart', headers=h, data=body)
    print(f"Subido {os.path.basename(filepath)}: {r.status_code}")
    return r.json().get('id')

def unpack_docx(src, out_dir):
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    with zipfile.ZipFile(str(src), 'r') as z:
        z.extractall(out_dir)

def pack_docx(src_dir, out_path):
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src_dir):
            for f in files:
                fp = os.path.join(root, f)
                z.write(fp, os.path.relpath(fp, src_dir))

def replace_xml(xml_path, reemplazos):
    with open(xml_path, 'r', encoding='utf-8') as f:
        content = f.read()
    for old, new in reemplazos.items():
        if old and old in content:
            content = content.replace(old, str(new))
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(content)

def parse_fecha(s):
    if not s:
        return '', '', ''
    s2 = s.replace(' del ', ' de ')
    p = s2.split(' de ')
    return (p[0].strip(), p[1].strip(), p[2].strip()) if len(p) >= 3 else ('', '', '')

def depto_parts(depto):
    d = str(depto)
    if len(d) >= 2:
        return d[:-1], d[-1]
    return d, ''

def generar_contrato(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'contrato')
    unpack_docx(DOCS_BASE['contrato'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')

    nivel = c.get('nivel', '').lower().strip()
    dia_ap, mes_ap, _ = parse_fecha(c.get('fechaApartado', ''))
    _, mes_en, _ = parse_fecha(c.get('fechaEnganche', ''))
    dia_fi, mes_fi, anio_fi = parse_fecha(c.get('fechaFiniquito', ''))
    dia_co, mes_co, anio_co = parse_fecha(c.get('fechaContrato', ''))

    eng_l = c.get('engancheLetra', '').replace(' pesos 00/100 M.N.', '').strip().split()
    fin_l = c.get('finiquitoLetra', '').replace(' pesos 00/100 M.N.', '').strip().split()
    pre_l = c.get('precioLetra', '').replace(' pesos 00/100 M.N.', '').strip()

    eng_num = str(c.get('enganche', '350000')).replace(',', '').replace('.', '')
    pre_num = str(c.get('precio', '3500000')).replace(',', '').replace('.', '')
    fin_num = str(c.get('finiquito', '3130000')).replace(',', '').replace('.', '')

    d1, d2 = depto_parts(c['depto'])

    nombre = c['nombre'].strip()
    if nombre.startswith('C ') or nombre.startswith('c '):
        nombre = nombre[2:]
    nombre_inv = c.get('nombreInvertido', nombre).strip()

    reemplazos = {
        'JUAN CARLOS CORDOBA MANZANARES': nombre,
        'JUAN CARLOS MANZANARES CORDOBA': nombre_inv,
        'MACJ820316HDFNRN09': c.get('curp', ''),
        'MACJ820316DZ5': c.get('rfc', '') or 'SIN RFC',
        'Credencial para Votar No.2169312321': f"Credencial para Votar No.{c.get('ine', '')}",
        '>60<': f'>{c["depto"]}<',  # Full depto number in declarations
        '>603<': f'>{c["depto"]}<',
        'ubicado en el nivel s': f'ubicado en el nivel {nivel[0]}' if nivel else 'ubicado en el nivel ',
        '>exto<': f'>{nivel[1:]}<' if len(nivel) > 1 else '><',
        '>70 <': f'>{c.get("m2", "70")} <',
        '>70<': f'>{c.get("m2", "70")}<',
        '>50<': f'>{pre_num[1:3] if len(pre_num) > 2 else "50"}<',
        '>MILLONES QUINIENTOS MIL<': f'>{pre_l.upper()}<',
        '>26<': f'>{dia_ap}<',
        '>Febrero<': f'>{mes_ap}<',
        '>3<': f'>{eng_num[0] if eng_num else "3"}<',
        '>5<': f'>{eng_num[1] if len(eng_num) > 1 else "5"}<',
        '>0,000<': f'>{eng_num[2:] if len(eng_num) > 2 else "0,000"}<',
        '>Trescientos<': f'>{eng_l[0].capitalize()}<' if eng_l else '>Trescientos<',
        '>cincuenta <': f'>{" ".join(eng_l[1:3])} <' if len(eng_l) > 1 else '>cincuenta <',
        '>Marzo<': f'>{mes_en}<',
        '>13<': f'>{fin_num[1:3] if len(fin_num) > 2 else "13"}<',
        '>Tres<': f'>{fin_l[0].capitalize()}<' if fin_l else '>Tres<',
        '> millones <': f'> {fin_l[1]} <' if len(fin_l) > 1 else '> millones <',
        '>ciento treinta<': f'>{" ".join(fin_l[2:4])}<' if len(fin_l) > 2 else '>ciento treinta<',
        '>junio<': f'>{mes_fi}<',
        '>1<': f'>{dia_fi[0] if dia_fi else "1"}<',
        '>8<': f'>{dia_fi[1] if len(dia_fi) > 1 else "8"}<',
        '>8 <': f'>{dia_fi[1] if len(dia_fi) > 1 else "8"} <',
        '18 de ': f'{dia_co} de ',
        '>Junio<': f'>{mes_co}<',
        '>C<': '><',
        'Campeche 315 Colonia Condesa C.P. 06100 Ciudad de México': 'Av. Magdalena 507, Col. del Valle Centro, Benito Juarez, 03100 Ciudad de Mexico CDMX',
        'ol. Santa Maria, LA RIBERA 06400, ': f'{c.get("domicilio", "")} ',
        'cuahutemoc': '',
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"1_Contrato_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_apartado(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'apartado')
    unpack_docx(DOCS_BASE['apartado'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    nombre = c['nombre'].strip()
    dia_ap, mes_ap, anio_ap = parse_fecha(c.get('fechaApartado', ''))
    reemplazos = {
        'a _____': f'a {dia_ap}',
        '>____________<': f'>{mes_ap}<',
        '>202<': f'>{anio_ap}<' if anio_ap else '>202<',
        # Nombre del comprador (campo de texto largo)
        '____________________________________': nombre,
        # Monto en letra - reemplazar el campo entre paréntesis
        '(_____________________________________': '(Veinte mil pesos 00/100 M.N.',
        # Segundo campo de depto al final
        'del departamento no.': f'del departamento no.',
        '. _______': f'. {c["depto"]}',
        '>______<': f'>{c["depto"]}<',
        # Segundo campo depto al final del documento
        'departamento no.</w:t></w:r>': f'departamento no.</w:t></w:r>',
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"2_Apartado_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_acta(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'acta')
    unpack_docx(DOCS_BASE['acta'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    nombre = c['nombre'].strip()
    fecha = c.get('fechaEntrega', c.get('fechaContrato', ''))
    dia_e, mes_e, anio_e = parse_fecha(fecha)
    d1, d2 = depto_parts(c['depto'])
    reemplazos = {
        'Ciudad de México a ___': f'Ciudad de México a {dia_e}',
        '>____________<': f'>{mes_e}<',
        '>20<': f'>{anio_e[:2] if anio_e else "20"}<',
        '>21<': f'>{anio_e[2:] if len(anio_e) > 2 else "26"}<',
        '>10<': f'>{d1}<',
        '>2<': f'>{d2}<',
        'Nombre y Firma': nombre,
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"3_Acta_Entrega_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_poliza(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'poliza')
    unpack_docx(DOCS_BASE['poliza'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    nombre = c['nombre'].strip()
    dia_co, mes_co, anio_co = parse_fecha(c.get('fechaContrato', ''))
    d1, d2 = depto_parts(c['depto'])
    reemplazos = {
        '____________________________________________________': nombre,
        '>10<': f'>{d1}<',
        '>2<': f'>{d2}<',
        '___ del mes de ______________ del año _________': f'{dia_co} de {mes_co} del {anio_co}',
        '\u201cEL CLIENTE\u201d': nombre,
        'Nombre: _________________________________         Departamento: ______________________': f'Nombre: {nombre}         Departamento: {c["depto"]}',
        'Fecha: __________________________________         Teléfono: ___________________________': f'Fecha: {c.get("fechaEntrega", c.get("fechaContrato",""))}         Teléfono: ___________________________',
        'Ciudad de México, a ____ de __________________ del ____________.': f'Ciudad de México, a {c.get("fechaContrato", "")}.',
        '___ DEL MES DE ____ DEL AÑO_____.': f'{c.get("fechaContrato", "")}.',
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"4_Poliza_Garantia_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_responsiva(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'responsiva')
    unpack_docx(DOCS_BASE['responsiva'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    d1, d2 = depto_parts(c['depto'])
    reemplazos = {'>10<': f'>{d1}<', '>2<': f'>{d2}<'}
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"5_Responsiva_Mudanza_Depto{c['depto']}_{c['nombre'].replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_reporte(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'reporte')
    unpack_docx(DOCS_BASE['reporte'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    d1, d2 = depto_parts(c['depto'])
    reemplazos = {'>10<': f'>{d1}<', '>2<': f'>{d2}<'}
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"6_Reporte_Reparacion_Depto{c['depto']}_{c['nombre'].replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_aviso(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'aviso')
    unpack_docx(DOCS_BASE['aviso'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    nombre = c['nombre'].strip()
    fecha_entrega = c.get('fechaEntrega', c.get('fechaContrato', ''))
    _, mes_e, anio_e = parse_fecha(fecha_entrega)
    dia_ent, mes_ent, anio_ent = parse_fecha(fecha_entrega)
    reemplazos = {
        # Fecha del aviso: "CDMX 15 DE MAYO DEL 2026"
        'CDMX 15 DE MAYO DEL 2026': f'CDMX {dia_ent.upper()} DE {mes_ent.upper()} DEL {anio_ent}' if dia_ent else 'CDMX',
        'Lety / Fer': nombre,
        'no. 604': f'no. {c["depto"]}',
        'junio del 2026': f'{mes_e} del {anio_e}' if mes_e else 'junio del 2026',
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"7_Aviso_Mantenimiento_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_cfe(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'cfe')
    unpack_docx(DOCS_BASE['cfe'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    nombre = c['nombre'].strip()
    reemplazos = {
        'Hola!!!': f'Hola {nombre}!!!',
        '(tu # de depto.)': c['depto'],
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"8_Requisitos_CFE_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

def generar_bienvenida(c, tmp_dir):
    out_dir = os.path.join(tmp_dir, 'bienvenida')
    unpack_docx(DOCS_BASE['bienvenida'], out_dir)
    xml = os.path.join(out_dir, 'word', 'document.xml')
    nombre = c['nombre'].strip()
    dia_co, mes_co, anio_co = parse_fecha(c.get('fechaContrato', ''))
    reemplazos = {
        'Gabriel y Esmeralda': nombre,
        '20 MARZO 2024': f'{dia_co} DE {mes_co.upper()} DE {anio_co}' if dia_co else '20 MARZO 2024',
    }
    replace_xml(xml, reemplazos)
    out = os.path.join(tmp_dir, f"9_Bienvenida_Depto{c['depto']}_{nombre.replace(' ','_')}.docx")
    pack_docx(out_dir, out)
    return out

@app.route('/api/leer-ine', methods=['POST'])
def leer_ine():
    try:
        data = request.json
        client = anthropic.Anthropic()
        media_type = data['mediaType']
        is_pdf = 'pdf' in media_type.lower()

        if is_pdf:
            content_block = {
                'type': 'document',
                'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': data['image']}
            }
        else:
            content_block = {
                'type': 'image',
                'source': {'type': 'base64', 'media_type': media_type, 'data': data['image']}
            }

        response = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=500,
            messages=[{'role': 'user', 'content': [
                content_block,
                {'type': 'text', 'text': 'Analiza esta credencial INE mexicana. Responde SOLO JSON sin backticks:\n{"nombre":"NOMBRE(S) APELLIDO1 APELLIDO2 en mayusculas","curp":"CURP 18 chars","rfc":"RFC o vacio","ine":"clave de elector","domicilio":"domicilio completo","fechaNac":"DD/MM/YYYY"}'}
            ]}]
        )
        text = ''.join(b.text for b in response.content if hasattr(b, 'text'))
        return jsonify(json.loads(re.sub(r'```json|```', '', text).strip()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generar', methods=['POST'])
def generar():
    try:
        c = request.json
        tmp = tempfile.mkdtemp()
        try:
            archivos = [
                generar_contrato(c, tmp),
                generar_apartado(c, tmp),
                generar_acta(c, tmp),
                generar_poliza(c, tmp),
                generar_responsiva(c, tmp),
                generar_reporte(c, tmp),
                generar_aviso(c, tmp),
                generar_cfe(c, tmp),
                generar_bienvenida(c, tmp),
            ]
            token = get_drive_token()
            if not token:
                return jsonify({'error': 'Drive no autorizado. Ve a /oauth/login primero.'}), 401
            folder_id = crear_carpeta_drive(f"Depto-{c['depto']} - {c['nombre']}", CONTRATOS_FOLDER_ID, token)
            upload_to = folder_id or CONTRATOS_FOLDER_ID
            for a in archivos:
                subir_archivo_drive(a, upload_to, token)
            return jsonify({'ok': True, 'folderUrl': f"https://drive.google.com/drive/folders/{upload_to}"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Uptown Living - http://localhost:5000")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
