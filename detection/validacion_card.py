# Validación del modelo - card HTML para Transparencia
_validacion_html = """
<div class="card" id="validacion">
<h3>Validación del modelo</h3>
<p class="caption" style="font-size:.84rem;color:#334155;line-height:1.65">
El radar se valida con <b>dos métodos que prueban cosas distintas</b>.
No compiten: uno verifica la <b>mecánica</b>, el otro el <b>alcance</b>.
</p>
<table style="width:100%;border-collapse:collapse;margin:8px 0;font-size:.82rem">
<tr style="background:#f8fafc">
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #c2410c">Método</th>
<th style="text-align:center;padding:6px 10px;border-bottom:2px solid #c2410c">Resultado</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #c2410c">Qué prueba</th>
</tr>
<tr>
<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">🔬 <b>ARI sintético</b></td>
<td style="text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0"><span style="color:#16a34a;font-weight:700">1,000</span></td>
<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">La mecánica de clustering detecta correctamente coordinación simulada (6 escenarios).</td>
</tr>
<tr>
<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">🌍 <b>EUvsDisinfo</b></td>
<td style="text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0"><span style="color:#ea580c;font-weight:700">0% / 0%</span></td>
<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">Dominios rusos/chinos (2015-23) fuera de <b>scope actual</b>. RT en Español capturado (567 ev) sin amplificación.</td>
</tr>
<tr>
<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">📊 <b>Dominios encontrados</b></td>
<td style="text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0"><span style="color:#2563eb;font-weight:700">0 de 17 ES</span></td>
<td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">De los <b>17 dominios</b> en castellano (243 casos), ninguno amplifica en clusters del radar.</td>
</tr>
</table>
<div style="margin-top:10px;padding:10px 14px;background:#fffbeb;border-left:4px solid #d97706;border-radius:4px">
<b style="color:#92400e">⚙️ En evolución — no es un fallo.</b> El radar monitoriza
Ceuta/Marruecos/España/EEUU/Oriente Medio, no Ucrania/Rusia.
Los <b>243</b> casos en castellano (de 10.682 totales, 42 idiomas)
son el terreno que cubriremos al ampliar el catálogo.
<br><span style="font-size:.78rem;color:#78350f">Dataset EUvsDisinfo · benchmark externo, ejecutado cada ciclo.</span>
</div>
</div>
"""
