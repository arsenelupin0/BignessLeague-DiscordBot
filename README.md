# Bigness League Bot

Base inicial de un bot de Discord usando `discord.py`, con soporte para slash commands.

## Requisitos

- Python 3.11 o superior
- Un bot creado en el [Discord Developer Portal](https://discord.com/developers/applications)

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

## Configuracion

1. Crea tu archivo `.env` a partir de `.env.example`.
2. Define `DISCORD_TOKEN` con el token del bot.
3. Define `DISCORD_GUILD_ID` con el ID de tu servidor de pruebas.
4. Opcionalmente ajusta `BOT_PREFIX` si quieres usar otro prefijo para comandos de texto.
5. Ajusta `BOT_ENV` y `BOT_SYNC_SCOPE` segun el entorno.
6. Ajusta `BOT_DEFAULT_LOCALE` y `BOT_LOCALES_DIR` si quieres cambiar el idioma base o la carpeta de catalogos.
7. Ajusta las variables `BOT_LOG_*` si quieres mas o menos verbosidad.
8. Ajusta `BOT_TIMEZONE` si quieres interpretar las fechas y horas de los partidos en otra zona horaria.
   Puedes usar `local`, un offset como `+02:00`, o una zona IANA valida si tu entorno dispone de datos de zona horaria.
9. Si quieres cambiar los botones del mensaje inicial de los partidos, ajusta `BOT_MATCH_CHANNEL_TICKET_URL` y
   `BOT_MATCH_CHANNEL_RULES_URL`.
10. Si quieres usar la integracion nativa de tickets, configura `BOT_TICKET_FORUM_CHANNEL_ID` con el ID del foro donde
    el bot debe crear los posts internos de ticket. `BOT_TICKET_STATE_FILE` es opcional y define donde se guarda el
    estado persistente de tickets activos.
11. Si quieres activar la IA local para tickets, ajusta `BOT_TICKET_AI_*`. El bot soporta dos backends:
    `openai_compatible` para LM Studio y tambien para Ollama en modo OpenAI-compatible, y `ollama_native` para la API
    nativa de Ollama.
12. Si quieres usar `/ver_mi_equipo`, configura `BOT_GOOGLE_SERVICE_ACCOUNT_FILE`
    y `BOT_GOOGLE_SHEETS_SPREADSHEET_ID`. `BOT_GOOGLE_SHEETS_TEAM_SHEET_NAME` es opcional.
13. Si quieres sincronizar roles automaticamente desde `/hacer_fichaje` o `/asignar_rol_equipo_automatico`,
    ajusta `BOT_PARTICIPANT_ROLE_ID` y `BOT_PLAYER_ROLE_ID` con los roles base que deben recibir todos los jugadores.
14. Si quieres autoasignar esos roles de jugador al entrar al servidor cuando el miembro coincida con Google Sheets,
    deja `BOT_AUTO_ASSIGN_PLAYER_ROLES_ON_JOIN=true`.
15. Si quieres publicar automaticamente el aviso de salida de un club cuando un miembro pierda un rol de equipo,
    ajusta `BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID`.
16. Si quieres que las bajas retiren tambien roles de staff tecnico, ajusta `BOT_STAFF_CEO_ROLE_ID`,
    `BOT_STAFF_ANALYST_ROLE_ID`, `BOT_STAFF_COACH_ROLE_ID`, `BOT_STAFF_MANAGER_ROLE_ID`,
    `BOT_STAFF_SECOND_MANAGER_ROLE_ID` y `BOT_STAFF_CAPTAIN_ROLE_ID`.
17. Si quieres forzar una fuente concreta para la imagen de `/ver_mi_equipo`, ajusta `BOT_TEAM_PROFILE_FONT_PATH`.
    Lo recomendado es colocar la fuente dentro de `aa_resources/fonts/`.

Si defines `DISCORD_GUILD_ID`, los slash commands se sincronizan en ese servidor y aparecen casi al instante. Si lo
dejas vacio, se sincronizan globalmente y Discord puede tardar en propagarlos.

Para usar el comando de texto `!sync`, activa tambien `Message Content Intent` en el Developer Portal, dentro de la
seccion `Bot`.

Para usar la asignacion automatica de roles por nombre de miembro, activa tambien `Server Members Intent` en el
Developer Portal.

La sincronizacion ahora sigue una politica fija por proceso:

- `BOT_ENV=development` suele ir con `BOT_SYNC_SCOPE=guild`
- `BOT_ENV=production` suele ir con `BOT_SYNC_SCOPE=global`

El comando `!sync` solo permite el scope configurado en ese arranque. Si quieres cambiar entre `guild` y `global`,
cambia el `.env` y reinicia el bot. Asi evitas mezclar scopes por accidente.

## Ejecucion

```powershell
bigness-bot
```

Alternativamente:

```powershell
python -m bigness_league_bot.main
```

## Slash command incluido

- `/cerrar_canal accion:<opcion>`: aplica acciones de cierre sobre el canal actual.
- `/anadir_al_canal`: abre un selector filtrado para anadir roles al canal actual.
-
`/canal_de_jornada jornada:<numero> partido:<numero> minutos_cortesia:<numero> fecha:<texto> hora:<texto> bo_x:<numero> categoria:<division> equipo_1:<rol> equipo_2:<rol>`:
crea un canal de partido con permisos para ambos equipos.

- `/ver_mi_equipo`: busca tu equipo en Google Sheets a partir de tu rol de Discord y muestra su ficha.
- `/hacer_fichaje enlace_jugadores:<url> enlace_staff_tecnico:<url>`: importa jugadores, staff tecnico o ambos desde
  mensajes de Discord hacia Google Sheets.
- `/dar_de_baja discord_jugador:<texto>`: elimina completamente a un miembro como jugador y staff tecnico.
- `/dar_de_baja_jugador discord_jugador:<texto>`: elimina solo al jugador del roster.
- `/dar_de_baja_staff discord_staff:<texto>`: elimina solo sus cargos de `STAFF TÉCNICO`.
- `/asignar_rol_equipo_automatico equipo:<rol>`: revisa la hoja del equipo y sincroniza los roles en Discord.
- `/integracion_de_tickets`: publica el panel de soporte para abrir tickets desde un menu desplegable.

Opciones disponibles en `/cerrar_canal`:

- `Partido jugado`: deja el canal en modo solo lectura para el resto de roles y mantiene escritura para `Staff`,
  `Administrador` y `Ceo`. Tambien cambia el icono final del canal a `✅`.
- `Jornada cerrada`: oculta el canal para los roles no protegidos, deja acceso solo a `Staff`, `Administrador` y `Ceo`
  y cambia el icono final del canal a `🔒`.
- `Reabrir partido`: restaura la escritura para los roles que ya tenian acceso al canal y devuelve el icono final a `⚽`.
- `Eliminacion de canal`: pide confirmacion con botones y elimina el canal por completo.

Restricciones de `/cerrar_canal`:

- solo funciona en canales cuyo nombre cumpla `j[1-9][0-9]?-partido-[1-9][0-9]?`
- solo pueden usarlo miembros con alguno de estos roles: `Staff`, `Administrador`, `Ceo`
- las respuestas del comando son publicas

`/anadir_al_canal`:

- solo funciona en canales cuyo nombre cumpla `j[1-9][0-9]?-partido-[1-9][0-9]?`
- solo pueden usarlo miembros con alguno de estos roles: `Staff`, `Administrador`, `Ceo`
- muestra solo roles entre los separadores configurados en `BOT_CHANNEL_ACCESS_RANGE_START_ROLE_ID` y
  `BOT_CHANNEL_ACCESS_RANGE_END_ROLE_ID`
- incluye busqueda propia por nombre parcial, ID o mencion de rol

`/canal_de_jornada`:

- solo puede usarlo un miembro con `Staff`, `Administrador` o `Ceo`
- crea el canal con nombre `『𝗝』1️⃣『𝗣』2️⃣・⚽`
- oculta el canal para `@everyone`
- permite elegir la categoria de destino entre `Gold Division` y `Silver Division`
- recibe minutos de cortesia, fecha, hora y formato `BoX`
- da acceso de lectura y escritura a `Staff`, `Administrador`, `Ceo`, `equipo_1` y `equipo_2`
- interpreta `fecha` como `DD/MM/YYYY` o `YYYY-MM-DD`, y `hora` como `HH:MM`
- usa `BOT_TIMEZONE` para convertir fecha y hora al timestamp de Discord
- valida que los dos roles de equipo sean distintos y esten dentro del rango de roles configurado
- usa `BOT_GOLD_DIVISION_CATEGORY_ID` y `BOT_SILVER_DIVISION_CATEGORY_ID` para resolver las categorias reales
- envia automaticamente un mensaje inicial con menciones a ambos equipos, tres embeds informativos y botones URL para
  ticket y normativa

`/ver_mi_equipo`:

- sin parametros, usa tu rol de equipo dentro del rango configurado
- `Staff`, `Administrador` y `Ceo` pueden ademas pasar un rol de equipo explicito como parametro opcional
- si tienes varios roles de equipo, el bot muestra una botonera para que elijas cual consultar
- busca el bloque de tu equipo en la hoja de Google Sheets configurada
- toma la division directamente del nombre de la hoja
- lee el tracker desde el hipervinculo de la celda `Jugador`
- devuelve la ficha del equipo como una imagen PNG en un unico mensaje del bot
- adjunta botones para listar los trackers en el mismo mensaje o quitar la botonera
- permite fijar una fuente propia con `BOT_TEAM_PROFILE_FONT_PATH`, por ejemplo
  `aa_resources/fonts/MapleMono-NF-CN-Regular.ttf`

`/hacer_fichaje`:

- solo puede usarlo un miembro con `Staff`, `Administrador` o `Ceo`
- recibe `enlace_jugadores` y `enlace_staff_tecnico` como enlaces opcionales; debes indicar al menos uno
- ambos mensajes enlazados deben incluir siempre las cabeceras `Division:` y `Equipo:`
- ambos mensajes enlazados pueden venir encerrados en un bloque de codigo de Discord con triple backtick
- si indicas ambos enlaces, ambos deben apuntar a la misma `Division` y al mismo `Equipo`
- `enlace_jugadores` usa el formato `Division`, `Equipo` y bloques repetidos de jugador
- `enlace_staff_tecnico` usa el formato `Division`, `Equipo` y bloques repetidos de `Rol` y `Discord`
- en `enlace_staff_tecnico`, `Epic Name` y `Rocket In-Game Name` son opcionales; si faltan, el bot los copia desde el
  jugador con ese mismo `Discord` dentro del bloque del equipo
- si el `Discord` del staff no existe en la plantilla de jugadores del equipo, o aparece duplicado, el comando rechaza
  la operacion
- resuelve la hoja destino por el nombre de la division
- si el equipo ya existe, mezcla la plantilla actual con los nuevos fichajes
- si el equipo no existe, usa el primer bloque de equipo libre en esa hoja
- ordena la plantilla resultante de mayor a menor `MMR` antes de escribir
- rellena las filas sobrantes del bloque con `-`
- si no hay bloque libre o no caben todos los fichajes, rechaza la operacion
- para `staff tecnico`, localiza la fila por el valor de `Rol` dentro del bloque `STAFF TÉCNICO` y solo actualiza las
  columnas `Discord`, `Epic Name` y `Rocket In-Game Name`
- para `staff tecnico`, intenta asignar el rol de equipo y el rol tecnico que corresponda:
  `CEO`, `Mánager`/`Segundo Mánager`, `Coach`/`Analista` o `Capitán`
- si un miembro de staff cambia de rol tecnico, el bot retira los roles tecnicos configurados que ya no correspondan
- despues de escribir, intenta asignar automaticamente el rol general de participante y el rol del equipo a los
  miembros que ya esten en Discord, junto con el rol general de jugador

`/dar_de_baja`, `/dar_de_baja_jugador` y `/dar_de_baja_staff`:

- solo puede usarlo un miembro con `Staff`, `Administrador` o `Ceo`
- `/dar_de_baja` elimina al miembro del roster y de `STAFF TÉCNICO` si aparece en ambos sitios
- `/dar_de_baja_jugador` solo reescribe el roster; si el miembro sigue en `STAFF TÉCNICO`, conserva el rol de equipo
- `/dar_de_baja_staff` solo limpia sus filas de staff; si el miembro sigue como jugador, conserva `Participante`,
  `Jugador` y el rol de equipo
- si encuentra coincidencias en mas de un bloque de equipo, rechaza la operacion y muestra donde estan los duplicados
- al borrar filas, el bot rellena los huecos de Google Sheets con `-`
- despues intenta retirar en Discord solo los roles que dejan de corresponder segun el tipo de baja
- no modifica automaticamente la celda de fichajes restantes

`/asignar_rol_equipo_automatico`:

- solo puede usarlo un miembro con `Staff`, `Administrador` o `Ceo`
- recibe un rol de equipo dentro del rango configurado
- lee la plantilla actual del equipo desde Google Sheets
- intenta asignar en Discord `Participante`, `Jugador` y el rol de equipo a los jugadores
- intenta asignar el rol de equipo y los roles tecnicos correspondientes a `STAFF TÉCNICO`
- si un miembro de staff cambia de rol tecnico, retira los roles tecnicos configurados que ya no correspondan
- informa de miembros asignados, ya configurados, sin coincidencia y coincidencias ambiguas

Autoasignado al entrar al servidor:

- si `BOT_AUTO_ASSIGN_PLAYER_ROLES_ON_JOIN=true`, el bot revisa al entrar un miembro nuevo contra la plantilla de
  jugadores y `STAFF TÉCNICO` de Google Sheets
- si encuentra una unica coincidencia como jugador, anade `Participante`, `Jugador` y el rol de equipo
- si tambien aparece en `STAFF TÉCNICO`, anade el rol de equipo y los roles tecnicos que correspondan
- si no encuentra coincidencia, no hace nada
- si encuentra varias coincidencias, no asigna nada y lo deja en log como ambiguo
- si asigna rol de equipo a un jugador, publica el boletin automatico de fichaje
- `/asignar_rol_equipo_automatico` sigue siendo el metodo manual de reconciliacion para miembros ya dentro del servidor
  o cambios masivos

Aviso automatico al perder rol de equipo:

- si un miembro pierde uno o varios roles de equipo, el bot publica un embed en
  `BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID`
- el embed intenta resolver la division real desde Google Sheets y usa como thumbnail el hipervinculo de la celda del
  equipo
- si el equipo no tiene imagen enlazada, usa el icono del servidor como fallback
- este flujo solo escucha la perdida de roles de equipo; no se activa por cambios de roles tecnicos

`/integracion_de_tickets`:

- solo puede usarlo un miembro con el rol `Ceo`/`CEO`
- publica en el canal actual un panel persistente con menu desplegable para abrir tickets
- al seleccionar una categoria, el bot crea un post dentro del foro configurado por `BOT_TICKET_FORUM_CHANNEL_ID`
- el post aplica la etiqueta del foro que coincida con la categoria seleccionada
- el usuario continua la conversacion por DM con el bot
- los mensajes enviados por DM se reenvian al hilo del foro
- las respuestas del staff escritas en el hilo del foro se envian al usuario por DM
- cada usuario solo puede tener un ticket activo a la vez
- el hilo incluye botones persistentes para `🔒 Cerrar ticket` y `🔏 Cerrar con razón`
- el estado de tickets activos se guarda en `BOT_TICKET_STATE_FILE`
- el foro usa las etiquetas de categoria y las etiquetas de estado `🔓 Abierto` / `🔒 Cerrado`

Etiquetas esperadas en el foro de tickets:

- `Soporte general`
- `Competicion`
- `Mercado`
- `Streaming`
- `Apelaciones`
- `Bot`
- `Social`
- `🔓 Abierto`
- `🔒 Cerrado`

## IA local para tickets

La base inicial de IA local usa Ollama por HTTP y una base de conocimiento en JSON. No depende del sistema operativo:
el bot solo necesita poder acceder a `BOT_TICKET_AI_BASE_URL` o, en modo legacy, a `BOT_TICKET_AI_OLLAMA_BASE_URL`.

Variables de entorno principales:

- `BOT_TICKET_AI_ENABLED`: activa o desactiva la carga del servicio de IA local
- `BOT_TICKET_AI_AUTO_REPLY_ENABLED`: permite contestacion automatica en las categorias seguras configuradas
- `BOT_TICKET_AI_PROVIDER`: `openai_compatible` u `ollama_native`
- `BOT_TICKET_AI_BASE_URL`: URL base del backend local
- `BOT_TICKET_AI_API_KEY`: clave local para backends OpenAI-compatible como LM Studio u Ollama
- `BOT_TICKET_AI_MODEL`: modelo local, recomendado `qwen2.5:3b`
- `BOT_TICKET_AI_MAX_OUTPUT_TOKENS`: limite de salida de la respuesta estructurada
- `BOT_TICKET_AI_AUTO_REPLY_MIN_CONFIDENCE`: umbral minimo para responder automaticamente al usuario
- `BOT_TICKET_AI_KNOWLEDGE_BASE_FILE`: JSON estructurado con la base de conocimiento
- `BOT_TICKET_AI_SYSTEM_PROMPT_FILE`: prompt del sistema editable sin tocar codigo
- `BOT_TICKET_AI_AUTOREPLY_CATEGORIES`: categorias seguras separadas por comas

Recursos incluidos:

- `aa_resources/ticket_ai/knowledge_base.json`: ejemplo inicial de base de conocimiento
- `aa_resources/ticket_ai/system_prompt.txt`: prompt del sistema para la IA local

Flujo actual de la configuracion:

1. El bot carga la base de conocimiento JSON.
2. Recupera entradas relevantes por coincidencia lexica segun categoria y mensaje.
3. Llama al backend local con un prompt acotado y salida JSON estructurada.
4. La respuesta devuelve `answer`, `confidence`, `should_escalate`, `reason` y `used_entry_ids`.
5. Cuando el ticket entra por DM, el bot puede responder automaticamente si la categoria esta permitida y la
   confianza supera el umbral configurado.
6. El hilo interno recibe siempre una traza de la respuesta IA o del fallo del backend local.

Configuracion recomendada en Windows con LM Studio:

```dotenv
BOT_TICKET_AI_ENABLED=true
BOT_TICKET_AI_AUTO_REPLY_ENABLED=true
BOT_TICKET_AI_PROVIDER=openai_compatible
BOT_TICKET_AI_BASE_URL=http://127.0.0.1:1234/v1
BOT_TICKET_AI_API_KEY=lm-studio
BOT_TICKET_AI_MODEL=qwen2.5-3b-instruct
```

Si el bot corre en la misma maquina que LM Studio, usa `127.0.0.1` en vez de la IP `192.168.x.x`. Es mas seguro y
evita depender de la red local.

Configuracion recomendada en Debian con Ollama usando la misma ruta OpenAI-compatible:

```dotenv
BOT_TICKET_AI_ENABLED=true
BOT_TICKET_AI_AUTO_REPLY_ENABLED=true
BOT_TICKET_AI_PROVIDER=openai_compatible
BOT_TICKET_AI_BASE_URL=http://127.0.0.1:11434/v1
BOT_TICKET_AI_API_KEY=ollama
BOT_TICKET_AI_MODEL=qwen2.5:3b
```

Ejemplo de arranque con Ollama:

```powershell
ollama pull qwen2.5:3b
ollama serve
```

Si prefieres usar la API nativa de Ollama en Debian, cambia:

```dotenv
BOT_TICKET_AI_PROVIDER=ollama_native
BOT_TICKET_AI_BASE_URL=http://127.0.0.1:11434
BOT_TICKET_AI_MODEL=qwen2.5:3b
```

Configuracion de Google Sheets:

- `BOT_GOOGLE_SERVICE_ACCOUNT_FILE`: ruta al JSON de la cuenta de servicio con acceso de lectura a la hoja
- para `/hacer_fichaje`, esa misma cuenta de servicio necesita tambien acceso de escritura
- `BOT_GOOGLE_SHEETS_SPREADSHEET_ID`: ID del documento de Google Sheets
- `BOT_PARTICIPANT_ROLE_ID`: rol general que se anade junto al rol del equipo cuando se sincronizan miembros
- `BOT_PLAYER_ROLE_ID`: rol general de jugador que tambien se anade junto al rol del equipo
- `BOT_AUTO_ASSIGN_PLAYER_ROLES_ON_JOIN`: activa o desactiva el autoasignado de esos roles a nuevos miembros si
  coinciden con la plantilla de jugadores de Google Sheets
- `BOT_TEAM_ROLE_REMOVAL_ANNOUNCEMENT_CHANNEL_ID`: canal donde se publica el aviso cuando un miembro pierde un rol de
  equipo
- `BOT_STAFF_CEO_ROLE_ID`, `BOT_STAFF_ANALYST_ROLE_ID`, `BOT_STAFF_COACH_ROLE_ID`, `BOT_STAFF_MANAGER_ROLE_ID`,
  `BOT_STAFF_SECOND_MANAGER_ROLE_ID`, `BOT_STAFF_CAPTAIN_ROLE_ID`: roles extra que las bajas y sincronizaciones pueden
  retirar si el Discord tambien aparece en `STAFF TÉCNICO`
- `BOT_GOOGLE_SHEETS_TEAM_SHEET_NAME`: hojas de equipo que el bot debe consultar, separadas por comas. Por defecto se
  limita a `GOLD DIVISIÓN S3,SILVER DIVISIÓN S3`.
- la hoja debe estar organizada por bloques de equipo con este esquema: titulo del equipo, cabecera `Jugador`,
  `Discord`, `Epic Name`, `Rocket In-Game Name`, `MMR`, hasta 6 jugadores y una fila de resumen con fichajes restantes
  y media del equipo
- el render de imagen usa `Pillow`, asi que tras actualizar dependencias conviene ejecutar `pip install -e .`
- si quieres una fuente concreta para ese render, deja el archivo `.ttf`, `.ttc` u `.otf` dentro de
  `aa_resources/fonts/` y apunta `BOT_TEAM_PROFILE_FONT_PATH` a esa ruta relativa

## Localizacion

El bot carga sus textos desde `aa_resources/locales/`.

- `aa_resources/locales/es-ES.json`: catalogo base en espanol
- `aa_resources/locales/en-US.json`: ejemplo de segundo idioma
- `BOT_DEFAULT_LOCALE`: locale de fallback del bot
- `BOT_LOCALES_DIR`: directorio donde se cargan los catalogos

La localizacion cubre:

- nombres y descripciones de slash commands
- opciones visibles de comandos y componentes
- mensajes de respuesta, validacion y error

Para anadir un idioma nuevo, crea otro JSON con el nombre del locale de Discord, por ejemplo `fr.json` o `fr-FR.json`,
y replica las mismas claves.

Las claves no se referencian ya como cadenas crudas en el codigo. El flujo recomendado es:

1. Edita `aa_resources/locales/es-ES.json`.
2. Regenera el modulo tipado:

```powershell
python aa_scripts\i18n\generate_i18n_keys.py --catalog aa_resources\locales\es-ES.json --output src\bigness_league_bot\infrastructure\i18n\keys.py
```

3. Usa las claves desde `I18N`, por ejemplo `I18N.actions.channel_management.add_roles_summary`.

Esto te da autocompletado en IntelliJ IDEA y evita typos en las rutas de traduccion.

## Comandos de desarrollo

- `!sync guild`: fuerza la sincronizacion de slash commands en la guild configurada.
- `!sync global`: fuerza la sincronizacion global.
- `!sync prune guild`: elimina todos los slash commands remotos del scope guild configurado.
- `!sync prune global`: elimina todos los slash commands remotos del scope global.
- `!sync prune other`: elimina el scope opuesto al configurado en `BOT_SYNC_SCOPE`, util para limpiar duplicados entre
  `guild` y `global`.
- `!slashstatus`: muestra que comandos slash tiene cargados el bot localmente.

Los comandos de desarrollo usan el prefijo definido en `BOT_PREFIX` y estan limitados al propietario de la aplicacion.
`!sync` solo acepta el scope configurado en `BOT_SYNC_SCOPE`.

## Comandos de texto

- `!fichaje`: muestra la guia y plantilla para hacer una inscripcion o fichaje.
- `!inscripcion`: alias de `!fichaje`.

Este comando funciona tanto en canales del servidor como en hilos de ticket y en mensajes directos al bot.

## Estructura recomendada

```text
src/bigness_league_bot/
  app/               # arranque y bootstrap
  core/              # configuracion y primitivas compartidas
  application/       # casos de uso y servicios puros
  infrastructure/    # integraciones externas, como Discord
  presentation/      # cogs, comandos y adaptadores de entrada
```

La idea es que la logica reusable viva en `application/` y que `presentation/discord` solo traduzca interacciones de
Discord hacia esos casos de uso.

## Logs

El bot escribe logs en consola y en `aa_var/logs/bigness_league.log`.

Se registran:

- conexion y reconexion del bot
- entrada y salida de servidores
- slash commands recibidos y completados
- comandos de texto recibidos y completados
- errores de slash commands y comandos de texto
- todos los mensajes, si activas `BOT_LOG_ALL_MESSAGES=true`

## Diagnostico rapido si `/` no muestra comandos

1. Reinicia el bot y revisa la consola.
2. Debes ver una linea como `Sincronizacion completada: scope=guild:... total=...`.
3. Si no aparece, el bot no esta llegando a sincronizar.
4. Si aparece pero Discord no muestra nada, reinvita la aplicacion asegurando el scope `applications.commands`.
5. Si quieres forzarlo manualmente, usa `!sync guild`.
