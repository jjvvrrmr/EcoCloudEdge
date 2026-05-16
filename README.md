# EcoCloud Edge

> Plataforma cloud privada y sostenible sobre clúster de Raspberry Pi 4B con k3s  
> TFG — CFGS Administración de Sistemas Informáticos en Red (ASIR) · Madrid 2025-2026

[![Validate](../../actions/workflows/validate.yml/badge.svg)](../../actions/workflows/validate.yml)
[![Longhorn](https://img.shields.io/badge/Storage-Longhorn_v1.7.2-orange?logo=data:image/svg+xml;base64,PHN2Zy8+)](https://longhorn.io)
[![Ansible](https://img.shields.io/badge/Automation-Ansible-red?logo=ansible)](https://www.ansible.com)
[![Raspberry Pi](https://img.shields.io/badge/Hardware-Raspberry%20Pi%204B-C51A4A?logo=raspberrypi)](https://www.raspberrypi.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Power](https://img.shields.io/badge/Consumo-28W_máx-green?logo=leaflet)](https://github.com/jjvvrrmr/EcoCloudEdge)
[![Nodes](https://img.shields.io/badge/Nodes-4×_RPi_4B-blue?logo=kubernetes)](https://github.com/jjvvrrmr/EcoCloudEdge)

---

## ¿Qué es esto?

Un clúster de **4 Raspberry Pi 4B** (4 GB RAM cada una) que ejecuta una nube privada completa:
almacenamiento colaborativo, autenticación centralizada, DNS con bloqueo de rastreadores,
inferencia de IA local y monitorización en tiempo real. Todo con software libre, sin salida a
internet para los datos y por menos de 200 € de hardware.

**Consumo total del clúster a plena carga: < 28 W** (frente a los >400 W de un servidor 1U convencional).

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Orquestación | k3s v1.34.6 (Kubernetes ligero) |
| Almacenamiento | Longhorn v1.7.2 |
| Ingress / Proxy | Traefik |
| LoadBalancer | MetalLB v0.14.3 |
| Identidad | LLDAP (directorio LDAP) |
| DNS + Seguridad | AdGuard Home |
| Almacenamiento colaborativo | Nextcloud + MariaDB 10.11 |
| IA On-Premise | Ollama + TinyLlama 1.1B-Q4 |
| Middleware | Python 3.10 (Alpine) |
| Monitorización | Prometheus + Grafana |

---

## Estructura del repositorio

```
EcoCloudEdge/
├── ansible/
│   ├── inventory.ini.example   # Copia como inventory.ini y ajusta IPs
│   ├── secrets.yml.example     # Copia este archivo con tus contraseñas
│   ├── site.yml                # Playbook maestro (6 hitos)
│   └── roles/
│       ├── base/               # Hito 1: SO, cgroups, iSCSI, swap
│       ├── k3s_master/         # Hito 1: Control Plane
│       ├── k3s_worker/         # Hito 1: Workers
│       ├── longhorn/           # Hito 2: Almacenamiento distribuido
│       ├── traefik/            # Hito 2: Ingress Controller
│       ├── metallb/            # Hito 2: LoadBalancer bare-metal
│       ├── lldap/              # Hito 3: Identidad LDAP + AdGuard DNS
│       ├── nextcloud/          # Hito 4: MariaDB + Nextcloud
│       ├── ollama/             # Hito 5: IA + Middleware Python
│       └── monitoring/         # Hito 6: Prometheus + Grafana
├── manifests/                  # YAMLs puros para aplicación manual
│   ├── 01-namespaces/
│   ├── 02-longhorn/
│   ├── 03-traefik/
│   ├── 04-metallb/
│   ├── 05-lldap/
│   ├── 06-adguard/
│   ├── 07-mariadb/
│   ├── 08-nextcloud/
│   ├── 09-ollama/
│   └── 10-monitoring/
├── middleware/
│   ├── main.py                 # Código Python del webhook Nextcloud→Ollama
│   └── Dockerfile
├── docs/
│   ├── architecture.md         # Topología y decisiones de diseño
│   └── troubleshooting.md      # Incidencias reales con causa raíz y solución
├── .github/workflows/
│   └── validate.yml            # CI: lint + validación + secret scan
├── .gitignore
└── README.md
```

---

## GUÍA DE DESPLIEGUE COMPLETA

### PARTE 0 — Limpieza del entorno (si ya hubo instalación previa)

Si las Raspberry Pi tienen restos de una instalación anterior de k3s o Longhorn, hay que
limpiarlas antes de empezar. Si las placas son completamente nuevas, salta al Paso 1.

Ejecutar en los 4 nodos (conectar por SSH a cada uno):

```bash
# Desinstalar k3s del nodo maestro (solo en node1)
/usr/local/bin/k3s-uninstall.sh

# Desinstalar el agente k3s de los workers (node2, node3, node4)
/usr/local/bin/k3s-agent-uninstall.sh

# Detener procesos remanentes y remover enlaces activos
sudo systemctl stop k3s || true
sudo systemctl stop k3s-agent || true
sudo killall k3s || true

# Eliminación de directorios de datos, archivos y volúmenes persistentes
sudo rm -rf /var/lib/longhorn/
sudo rm -rf /var/lib/rancher/
sudo rm -rf /var/lib/kubelet/
sudo rm -rf /var/lib/cni/
sudo rm -rf /etc/rancher/
sudo rm -rf /run/k3s/
sudo rm -rf /run/flannel/
sudo rm -rf /var/log/pods/
sudo rm -rf /var/log/containers/

# Limpieza agresiva de reglas de red
sudo iptables -F
sudo iptables -X
sudo iptables -t nat -F
sudo iptables -t nat -X
sudo iptables -t mangle -F
sudo iptables -t mangle -X
sudo iptables -t raw -F
sudo iptables -t raw -X
sudo iptables -P INPUT ACCEPT
sudo iptables -P FORWARD ACCEPT
sudo iptables -P OUTPUT ACCEPT

# Eliminación de interfaces de red virtuales huérfanas
sudo ip link delete cni0 || true
sudo ip link delete flannel.1 || true
sudo ip link delete kube-ipvs0 || true
sudo ip link delete dummy0 || true

# Reiniciar cada nodo para refrescar el kernel
sudo reboot
```

Esperar a que los 4 nodos vuelvan a estar accesibles por SSH antes de continuar.

---

### PARTE 1 — Preparar la máquina de control (tu PC)

Estos comandos se ejecutan en tu ordenador, no en las Raspberry Pi.

**Paso 1.1 — Instalar dependencias**

```bash
# En Ubuntu / Debian
sudo apt update && sudo apt install -y ansible git

# En macOS
brew install ansible git

# En Windows → usar WSL2 con Ubuntu y aplicar los comandos de Ubuntu
```

**Paso 1.2 — Clonar el repositorio**

```bash
git clone https://github.com/jjvvrrmr/EcoCloudEdge.git
cd EcoCloudEdge
```

**Paso 1.3 — Crear la clave SSH (si no tienes una)**

Ansible necesita conectarse a las Raspberry Pi sin contraseña mediante clave SSH.
Si ya tienes una clave en `~/.ssh/id_ed25519`, salta este paso.

```bash
# Crear la clave (pulsa Enter en todas las preguntas para dejar sin passphrase)
ssh-keygen -t ed25519 -C "ecocloud-deploy"

# Copiar la clave pública a cada Raspberry Pi
# Sustituye 192.168.1.70 por la IP de cada nodo y "admin" por tu usuario
ssh-copy-id -i ~/.ssh/id_ed25519.pub admin@192.168.1.70
ssh-copy-id -i ~/.ssh/id_ed25519.pub admin@192.168.1.71
ssh-copy-id -i ~/.ssh/id_ed25519.pub admin@192.168.1.72
ssh-copy-id -i ~/.ssh/id_ed25519.pub admin@192.168.1.73

# Verificar que la conexión funciona sin contraseña
ssh admin@192.168.1.70 "echo OK"
ssh admin@192.168.1.71 "echo OK"
ssh admin@192.168.1.72 "echo OK"
ssh admin@192.168.1.73 "echo OK"
```

**Paso 1.4 — Configurar el inventario**

```bash
cp ansible/inventory.ini.example ansible/inventory.ini
```

Edita `ansible/inventory.ini` con las IPs reales de tus Raspberry Pi. El archivo ya
contiene las IPs del proyecto (192.168.1.70-73) y el usuario `admin`. Si los tuyos
son distintos, cámbialos aquí.

**Paso 1.5 — Crear el archivo de secretos**

El proyecto incluye una plantilla `ansible/secrets.yml.example`. Cópiala y rellena
los valores reales. Este archivo está en `.gitignore` y NUNCA se sube a Git.

```bash
cp ansible/secrets.yml.example ansible/secrets.yml
# Edita ansible/secrets.yml con tus contraseñas reales
```

El archivo tiene este aspecto una vez rellenado:

```yaml
lldap_jwt_secret: "cadena-aleatoria-larga-minimo-32-caracteres"
lldap_ldap_user_pass: "tu-contraseña-admin-lldap"
mysql_root_password: "tu-contraseña-root-mariadb"
mysql_password: "tu-contraseña-nextcloud-mariadb"
nextcloud_admin_password: "tu-contraseña-admin-nextcloud"
grafana_admin_password: "tu-contraseña-admin-grafana"
```

Para generar un `lldap_jwt_secret` seguro puedes usar:
```bash
openssl rand -hex 32
```

Los nombres van en minúsculas. Ansible distingue entre mayúsculas y minúsculas:
`LLDAP_JWT_SECRET` y `lldap_jwt_secret` son variables distintas y solo la segunda
funciona con los templates del proyecto.

---

### PARTE 2 — Despliegue automático con Ansible

**Paso 2.1 — Ejecutar el playbook completo**

Este único comando despliega los 6 hitos en orden:

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```

La flag `-e @ansible/secrets.yml` inyecta las contraseñas en memoria en tiempo de
ejecución. Sin ella, el playbook falla con `AnsibleUndefinedVariable`.

El despliegue completo tarda entre 30 y 60 minutos dependiendo de la velocidad de
red, porque cada nodo descarga imágenes de contenedor desde internet.

**Paso 2.2 — Si Ansible se congela durante la descarga de imágenes**

Es normal que Ansible parezca congelado durante varios minutos en las tareas de
Longhorn, MetalLB o Traefik. Las Raspberry Pi comparten 100 Mbps y las imágenes
son pesadas. No canceles el proceso. Si vence el timeout, Ansible es idempotente:
simplemente vuelve a lanzar el mismo comando y retomará donde se quedó:

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```

**Paso 2.3 — Si Ansible falla durante la descarga del modelo de IA**

La descarga de TinyLlama pesa ~650 MB. En una red de 100 Mbps compartida entre
los 4 nodos puede superar el tiempo límite configurado en Ansible y fallar con:

```
FAILED! => {"msg": "async task did not complete within the requested time - 1800s"}
```

Si ocurre, simplemente vuelve a lanzar el mismo comando. Ansible es idempotente:
retoma desde la tarea de descarga sin repetir nada de lo anterior:

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```

El rol de Ollama continuará donde se quedó y completará la descarga del modelo.

---

### PARTE 3 — Configuración del PC cliente (Windows)

Para acceder a los servicios por nombre de dominio desde tu ordenador, hay que
añadir los registros DNS locales al archivo hosts. Abrir PowerShell como Administrador:

```powershell
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" -Value "192.168.1.80 nubes.ecocloud.local"
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" -Value "192.168.1.80 monitor.ecocloud.local"
```

La IP `192.168.1.80` es la primera del pool MetalLB asignada por el clúster. Puedes
verificarla en node1 con:

```bash
sudo k3s kubectl get svc -A | grep LoadBalancer
```

---

### PARTE 4 — Configuración inicial de Nextcloud (primera vez)

1. Abre el navegador y navega a `http://nubes.ecocloud.local`
2. Rellena el formulario de instalación con estos datos:
   - **Cuenta de administración:** `admin` / (la contraseña de `nextcloud_admin_password`)
   - **Carpeta de datos:** `/data`
   - **Motor de base de datos:** MySQL/MariaDB
   - **Usuario de la BD:** `nextcloud_user`
   - **Contraseña de la BD:** (el valor de `mysql_password`)
   - **Nombre de la BD:** `nextcloud`
   - **Host de la BD:** `mariadb-svc:3306`
3. Haz clic en **Instalar**. Tarda unos minutos (PHP construye la BD).

**Integración con LLDAP (para autenticación centralizada):**

1. Menú → **Aplicaciones** → buscar "LDAP user and group backend" → **Activar**
2. Menú → **Configuraciones de administración** → **Integración LDAP/AD**
3. Rellenar:
   - **Host:** `lldap-svc`
   - **Puerto:** `3890`
   - **User DN:** `uid=admin,ou=people,dc=ecocloud,dc=local`
   - **Contraseña:** (el valor de `lldap_ldap_user_pass`)
   - **Base DN:** `dc=ecocloud,dc=local`
4. Clic en **Guardar credenciales** primero, después en **Probar Base DN**

---

### PARTE 5 — Acceso a Grafana

1. Abre `http://monitor.ecocloud.local`
2. Usuario: `admin` / Contraseña: (el valor de `grafana_admin_password`)
3. Ir a **Dashboards → Import** e importar estos IDs:
   - `1860` — Node Exporter Full (CPU, RAM, disco y red por nodo)
   - `13032` — k3s Cluster (estado del clúster, pods, deployments)
   - `13200` — Longhorn (volúmenes y réplicas)

---

### VERIFICACIÓN DE CADA HITO

```bash
# Hito 1 — Los 4 nodos en estado Ready
sudo k3s kubectl get nodes

# Hito 2 — Longhorn, Traefik y MetalLB operativos
sudo k3s kubectl get pods -n longhorn-system
sudo k3s kubectl get pods -n kube-system | grep traefik
sudo k3s kubectl get pods -n metallb-system

# Hito 3 — LLDAP Running (0 reinicios), AdGuard con IP externa
sudo k3s kubectl get pods -l "app in (lldap,adguard)"
sudo k3s kubectl get svc adguard-svc

# Hito 4 — Nextcloud respondiendo (HTTP 200)
curl -I -H "Host: nubes.ecocloud.local" http://192.168.1.80

# Hito 5 — IA respondiendo
sudo k3s kubectl run curl-test --image=curlimages/curl:latest --rm -i --tty -- \
  curl -s -X POST http://middleware-svc:5000 \
  -H "Content-Type: application/json" \
  -d '{"prompt":"¿De qué color es el cielo?"}'

# Hito 6 — Grafana accesible (HTTP 302 → login)
curl -I -H "Host: monitor.ecocloud.local" http://192.168.1.80
```

---

## OPCIÓN B — Manifiestos directos (sin Ansible)

Si prefieres aplicar los manifiestos manualmente desde node1, el orden es estricto:

```bash
# Hito 2 — Longhorn (el ConfigMap DEBE ir antes del despliegue)
sudo k3s kubectl create namespace longhorn-system
sudo k3s kubectl apply -f manifests/02-longhorn/longhorn-configmap.yaml
sudo k3s kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.7.2/deploy/longhorn.yaml

# Hito 2 — Traefik
sudo k3s kubectl apply -f manifests/03-traefik/traefik-helmchart.yaml

# Hito 2 — MetalLB (instalar primero, luego el pool)
sudo k3s kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.3/config/manifests/metallb-native.yaml
sudo k3s kubectl wait --namespace metallb-system --for=condition=ready pod --selector=app=metallb --timeout=120s
sudo k3s kubectl apply -f manifests/04-metallb/metallb-pool.yaml

# Hito 3 — LLDAP y AdGuard
# Los manifiestos usan variables ${VAR}. Exporta tus valores antes:
export LLDAP_JWT_SECRET="tu-secreto"
export LLDAP_LDAP_USER_PASS="tu-contraseña"
envsubst < manifests/05-lldap/lldap.yaml | sudo k3s kubectl apply -f -
sudo k3s kubectl apply -f manifests/06-adguard/adguard.yaml

# Hito 4 — MariaDB y Nextcloud
export MYSQL_ROOT_PASSWORD="tu-root"
export MYSQL_PASSWORD="tu-pass"
envsubst < manifests/07-mariadb/mariadb.yaml | sudo k3s kubectl apply -f -
sudo k3s kubectl apply -f manifests/08-nextcloud/nextcloud.yaml

# Hito 5 — Ollama y Middleware
sudo k3s kubectl apply -f manifests/09-ollama/ollama.yaml
sudo k3s kubectl apply -f manifests/09-ollama/middleware.yaml
# Esperar a que el pod esté Running y descargar el modelo:
# (en la opción B esto sí es manual porque no hay Ansible que lo gestione)
sudo k3s kubectl wait --for=condition=ready pod -l app=ollama --timeout=300s
sudo k3s kubectl exec deploy/ollama -- ollama pull tinyllama

# Hito 6 — Monitorización
export GRAFANA_ADMIN_PASSWORD="tu-contraseña"
envsubst < manifests/10-monitoring/monitoring-helmchart.yaml | sudo k3s kubectl apply -f -
```

---

## Seguridad

- **No hay secretos en este repositorio.** Las contraseñas van en `ansible/secrets.yml` (en `.gitignore`).
- Los manifiestos en `manifests/` usan variables `${VAR}` para sustituir con `envsubst`.
- Los templates Ansible usan variables Jinja2 `{{ var }}` resueltas en tiempo de ejecución con `-e @ansible/secrets.yml`.
- El CI tiene un job `secret-scan` que detecta contraseñas hardcodeadas antes de cualquier merge.

---

## Problemas conocidos

Ver [`docs/troubleshooting.md`](docs/troubleshooting.md) para todas las incidencias
documentadas durante el despliegue real, con causa raíz y solución verificada.

---

## Autores

- Alejandro Goyanes Matallanos
- Javier Maldonado Ramírez
- Iván Honrubia Llorente

CFGS ASIR · Madrid · Curso 2025–2026
