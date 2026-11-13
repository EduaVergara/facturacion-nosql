# Primera publicación en GitHub

Esta preparación habilita la colaboración sobre la etapa 6. La etapa 7 sigue
pendiente. Preparar-GitHub.ps1 agrega los archivos a tu proyecto del escritorio,
conserva configuración local y respalda los archivos que reemplaza.

En https://github.com/new crea facturacion-nosql. Elige Private si el acceso se
limita al grupo. No inicialices README, gitignore ni licencia en el remoto.
Copia la URL HTTPS del repositorio nuevo.

Para una carpeta que todavía no tiene Git:

```powershell
cd "$env:USERPROFILE\Desktop\facturacion-nosql"
git init
git branch -M main
git add .
git status --short
```

Revisa los archivos antes del commit. .env.example se incluye; .env,
local-config.json, cdk-outputs.json, respaldos y .actualizaciones se excluyen.
Ignorar no retira archivos que Git ya rastreaba: revisa esa situación si ya
habías realizado un commit anterior.

```powershell
git commit -m "Presenta Folio y su entorno colaborativo"
```

Si Git necesita identidad, configúrala localmente y repite el commit:

```powershell
git config user.name "Eduardo Vergara"
git config user.email (Read-Host "Correo asociado a GitHub")
git commit -m "Presenta Folio y su entorno colaborativo"
```

Conecta y publica:

```powershell
$urlRepositorio = Read-Host "URL HTTPS de tu repositorio"
git remote add origin $urlRepositorio
git push -u origin main
```

Si ya existe un repositorio o un remoto, consulta git status y git remote -v
antes de repetir estos pasos. Conserva los commits existentes. Completa la
autenticación mediante Git; no guardes contraseñas o tokens en archivos o URLs.

Actualiza la página y revisa README y Actions → Pruebas. El resultado de CI se
conoce después de ejecutarla. Para dar acceso, Settings → Collaborators permite
invitar a los usuarios del grupo. Usa ramas y pull requests según CONTRIBUTING.
Este paquete no envía invitaciones ni cambia permisos.

Fuentes:

- https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository
