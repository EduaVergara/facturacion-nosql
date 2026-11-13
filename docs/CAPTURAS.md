# Incorporar capturas originales

La preparación automática no pudo descargar las imágenes originales y el
control del navegador se bloqueó al no poder verificar la URL actual. No se
incluyen capturas simuladas ni enlaces rotos en el README.

Descarga desde la conversación tus capturas de punto de venta, historial y
comprobante académico con cliente general. Usa imágenes con datos ficticios y
sin documentos de identidad ni información privada del navegador.

Desde la raíz del proyecto, reemplaza las rutas por las de tus archivos:

```powershell
.\scripts\Agregar-Capturas.ps1 -PuntoVentaPath 'C:\ruta\venta.png' -HistorialPath 'C:\ruta\historial.png' -ComprobantePath 'C:\ruta\comprobante.png'
```

Puedes pasar solo las imágenes disponibles. El script comprueba que sean PNG,
las copia sin alterar píxeles a docs/capturas, respalda archivos reemplazados y
actualiza únicamente la sección Capturas del README. Después revisa las imágenes
y añade README y docs/capturas al commit.

Las tres imágenes originales identificadas en esta conversación son:

| Vista | Nombre original |
| --- | --- |
| Punto de venta | image(20261112-090658).png |
| Comprobante general | image(20261112-090734).png |
| Historial | image(20261112-090946).png |
