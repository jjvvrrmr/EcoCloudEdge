# Troubleshooting — EcoCloud Edge

> Este documento recoge **todas las incidencias reales** encontradas durante el despliegue
> del proyecto EcoCloud Edge (TFG 2025-2026). Cada problema incluye el síntoma exacto,
> la causa raíz técnica y la solución verificada en el entorno real.

---

## FASE 0 — Limpieza del entorno

### INC-00: Interbloqueos y comportamiento inesperado tras reinstalación

**Síntoma:**  
k3s o Longhorn se comportan de forma errática después de haber tenido una instalación
anterior. Los pods quedan en estados imposibles, las reglas de red no funcionan o los
volúmenes aparecen montados cuando no deberían.

**Causa raíz:**  
k3s y Longhorn dejan residuos que los scripts de desinstalación estándar no eliminan:
directorios de datos (`/var/lib/longhorn`), configuración CNI (`/var/lib/cni`, `/etc/cni`)
y reglas de `iptables` huérfanas que siguen activas en el kernel aunque el servicio ya
no exista.

**Solución:**  
Ejecutar la secuencia de limpieza agresiva en los 4 nodos antes de cualquier reinstalación:

```bash
# En node1 (nodo maestro)
/usr/local/bin/k3s-uninstall.sh

# En node2, node3, node4 (workers)
/usr/local/bin/k3s-agent-uninstall.sh

# En todos los nodos: purgar directorios residuales
sudo rm -rf /var/lib/longhorn
sudo rm -rf /var/lib/cni
sudo rm -rf /etc/cni
sudo rm -rf /opt/cni

# En todos los nodos: limpiar reglas de red huérfanas
sudo iptables -F
sudo iptables -t nat -F
sudo iptables -t mangle -F
sudo iptables -X

# En todos los nodos: reinicio físico para refrescar el kernel
sudo reboot
```

Esperar a que los 4 nodos vuelvan a estar accesibles por SSH antes de continuar.

---

## FASE 1 — Ansible y configuración

### INC-ANS-01: `AnsibleUndefinedVariable: 'lldap_jwt_secret'`

**Síntoma:**  
El playbook aborta en el Hito 3 con el error:
```
AnsibleUndefinedVariable: 'lldap_jwt_secret' is undefined
```

**Causa raíz:**  
Las contraseñas estaban definidas en un archivo `.env` con valores de relleno
(`CAMBIA_ESTO`) y en mayúsculas. Ansible (Jinja2) no lee archivos `.env` de forma
nativa y además distingue entre mayúsculas y minúsculas en los nombres de variable.
`LLDAP_JWT_SECRET` y `lldap_jwt_secret` son dos variables distintas para Ansible.

**Solución:**  
Eliminar el `.env` como fuente de variables para Ansible. Crear en su lugar un
diccionario YAML nativo en `ansible/secrets.yml` con los nombres en minúsculas
y contraseñas reales:

```yaml
lldap_jwt_secret: "cadena-aleatoria-larga"
lldap_ldap_user_pass: "contraseña-real"
mysql_root_password: "contraseña-real"
mysql_password: "contraseña-real"
nextcloud_admin_password: "contraseña-real"
grafana_admin_password: "contraseña-real"
```

Inyectar el archivo en tiempo de ejecución con la flag `-e`:
```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```

**Importante:** `ansible/secrets.yml` está en `.gitignore`. Nunca lo subas a Git.

---

### INC-ANS-02: Ansible congelado durante descargas de imágenes

**Síntoma:**  
Ansible se queda sin avanzar durante varios minutos, especialmente en las tareas de
Longhorn, MetalLB, Traefik o Nextcloud. Parece que ha muerto pero no da error.

**Causa raíz:**  
Limitación física de red. Las 4 Raspberry Pi comparten un enlace de 100 Mbps y
descargan imágenes de contenedor de forma simultánea, saturando el ancho de banda.
Los pods no están rotos: están en estado `Pulling image`. El timeout de Ansible
se alcanza antes de que terminen las descargas.

**Diagnóstico:**  
Mientras Ansible espera, abrir otra terminal y conectar a node1 para ver el estado real:
```bash
ssh admin@192.168.1.70
sudo k3s kubectl get pods -A
sudo k3s kubectl describe pod <nombre-del-pod-problemático>
# En la sección Events: verás "Pulling image..." si es un problema de red
```

**Solución:**  
Ansible es idempotente. Simplemente relanzar el playbook con el mismo comando:
```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```
Retomará desde el punto de fallo sin repetir lo que ya está hecho.

---

## FASE 2 — Almacenamiento y red (Hitos 2 y 3)

### INC-01: CrashLoopBackOff en LLDAP por permisos en Longhorn

**Síntoma:**
```
lldap-xxx   0/1   CrashLoopBackOff   6 (2m15s ago)   8m
```

**Causa raíz:**  
Longhorn provisiona el PVC con permisos `root` (UID 0). La imagen oficial de LLDAP
ejecuta el proceso como `UID 1000` y no puede escribir en `/data` para crear su base
de datos SQLite. El contenedor arranca, falla al escribir y entra en bucle de reinicio.

**Solución:**  
Añadir `securityContext.fsGroup: 1000` al spec del pod. El kubelet ajusta la propiedad
del grupo del volumen montado antes de arrancar el contenedor:
```yaml
spec:
  securityContext:
    fsGroup: 1000
```

---

### INC-02: Panic en Rust — variable LLDAP_LDAP_USER_PASS no documentada

**Síntoma en logs** (`kubectl logs deploy/lldap`):
```
thread 'main' panicked at server/src/main.rs:54:10:
The LDAP admin password must be initialized. Either set the `ldap_user_pass`
config value or the `LLDAP_LDAP_USER_PASS` environment variable.
```

**Causa raíz:**  
LLDAP v0.6.x hace obligatoria la variable `LLDAP_LDAP_USER_PASS` pero no la
documenta en la guía de inicio rápido. Sin ella, la aplicación arranca correctamente,
intenta inicializar la base de datos y lanza un panic de Rust al no encontrar la
contraseña del administrador.

**Solución:**  
Añadir la variable al Deployment:
```yaml
env:
  - name: LLDAP_LDAP_USER_PASS
    value: "tu-contraseña-admin"
```

---

### INC-03: ContainerCreating indefinido — interbloqueo RWO con RollingUpdate

**Síntoma:**
```
lldap-nuevo  0/1   ContainerCreating   0   99s   # bloqueado para siempre
lldap-viejo  0/1   CrashLoopBackOff    6   11m   # sigue girando
```

**Causa raíz:**  
La estrategia `RollingUpdate` (defecto de Kubernetes) intenta levantar el pod nuevo
antes de destruir el antiguo. El volumen Longhorn es `ReadWriteOnce` (RWO), lo que
significa que solo puede estar montado en un nodo a la vez. El pod antiguo mantiene
el bloqueo exclusivo del disco, impidiendo que el nuevo pod pueda montarlo.

**Solución:**  
Cambiar la estrategia de despliegue a `Recreate` en todos los Deployments que usen
volúmenes RWO. Recreate destruye el pod antiguo antes de crear el nuevo:
```yaml
spec:
  strategy:
    type: Recreate
```
Si el interbloqueo ya está activo, forzar la limpieza manual:
```bash
sudo k3s kubectl delete pod -l app=lldap
```

---

### INC-04: LoadBalancer de AdGuard en `<pending>` indefinido

**Síntoma:**
```
adguard-svc   LoadBalancer   10.43.77.33   <pending>   53:32625/TCP...
```

**Causa raíz:**  
k3s instalado con `--disable servicelb` no incluye el controlador Klipper. Sin un
controlador de LoadBalancer, los servicios de tipo `LoadBalancer` nunca reciben IP
externa en entornos bare-metal.

**Solución:**  
Desplegar MetalLB v0.14.3 como balanceador de carga bare-metal:
```bash
sudo k3s kubectl apply -f \
  https://raw.githubusercontent.com/metallb/metallb/v0.14.3/config/manifests/metallb-native.yaml
sudo k3s kubectl wait --namespace metallb-system \
  --for=condition=ready pod --selector=app=metallb --timeout=120s
sudo k3s kubectl apply -f manifests/04-metallb/metallb-pool.yaml
```

---

### INC-05: `kubectl get svc -l "app in (lldap,adguard)"` devuelve vacío

**Causa raíz:**  
Los manifiestos incluían `selector.app` (para que el Service encuentre los pods) pero
omitían `metadata.labels` en el propio objeto Service. El filtro `-l` actúa sobre los
metadatos del Service, no sobre su selector interno.

**Solución:**  
Añadir el bloque `labels` a los metadatos del Service:
```yaml
metadata:
  name: lldap-svc
  labels:
    app: lldap   # esto faltaba
```

---

### INC-06: Saturación de red — Longhorn degradando el clúster

**Síntoma:**  
Latencia alta en todos los servicios. Los pods tardan en responder. El ancho de banda
está saturado.

**Causa raíz:**  
La configuración por defecto de Longhorn establece 3 réplicas por volumen. Con una
red de 100 Mbps, el tráfico de sincronización entre réplicas ocupa todo el ancho de
banda disponible y degrada el rendimiento de todos los servicios.

**Solución:**  
Aplicar un ConfigMap que limite las réplicas a 2 **antes** de desplegar Longhorn:
```bash
sudo k3s kubectl create namespace longhorn-system
sudo k3s kubectl apply -f manifests/02-longhorn/longhorn-configmap.yaml
# Solo DESPUÉS aplicar el manifiesto principal:
sudo k3s kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.7.2/deploy/longhorn.yaml
```

---

## FASE 5 — IA On-Premise (Hito 5)

### INC-07: OOM Kill del pod de Ollama con modelos estándar

**Síntoma:**  
El pod de Ollama muere nada más arrancar o al intentar cargar el modelo. `dmesg`
en el nodo muestra `oom-kill`.

**Causa raíz:**  
Cada nodo tiene 4 GB de RAM. Tras SO + infraestructura k3s + Longhorn, quedan
aproximadamente 1.5–2 GB disponibles. Un modelo de 7B parámetros en FP16 requiere
14 GB: el OOMKiller del kernel lo termina instantáneamente.

**Solución:**  
Usar modelos cuantizados en formato GGUF y añadir límite explícito de memoria al
Deployment:
```bash
sudo k3s kubectl exec deploy/ollama -- ollama pull tinyllama    # ~670 MB
sudo k3s kubectl exec deploy/ollama -- ollama pull qwen2:0.5b  # ~400 MB
```
```yaml
resources:
  limits:
    memory: "2Gi"
```

---

### INC-08: Timeout de Ansible descargando el modelo de Ollama

**Síntoma:**
```
FAILED! => {"msg": "async task did not complete within the requested time - 600s"}
```

**Causa raíz:**  
El rol de Ollama tenía un límite `async: 600` (10 minutos). La descarga de TinyLlama
(~650 MB) a través de la red de 100 Mbps compartida entre los 4 nodos tarda más
de ese límite.

**Solución:**  
Ampliar el parámetro `async` a 1800 segundos (30 minutos) en
`ansible/roles/ollama/tasks/main.yml` (ya corregido en el repo):
```yaml
- name: "Descargar modelo TinyLlama"
  command: k3s kubectl exec deploy/ollama -- ollama pull tinyllama
  async: 1800
  poll: 30
```
Después, relanzar el playbook con el mismo comando. Ansible retoma desde la tarea
de descarga sin repetir nada de lo anterior. No es necesario hacer nada a mano:
```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```

---

## FASE 6 — Monitorización (Hito 6)

### INC-09: Node1 se congela durante el despliegue de Grafana

**Síntoma:**
```
UNREACHABLE! => {"msg": "Failed to connect to the host via ssh: Connection timed out"}
```
Ansible pierde la conexión SSH con node1 (192.168.1.70) durante el Hito 6.

**Causa raíz:**  
Al estar el nodo maestro gestionando k3s, la base de datos MariaDB, Nextcloud y
extrayendo el chart de kube-prometheus-stack simultáneamente, el consumo de RAM
superó los 4 GB disponibles. El OOMKiller comenzó a matar procesos y el sistema
operativo se congeló.

**Solución:**  
Reinicio forzado por corte de corriente (hard reset) de node1. Tras reconectar:
- k3s recuperó el clúster de forma autónoma
- Los pods que estaban Running volvieron a Running solos
- Relanzar Ansible con el mismo comando retomó desde el punto de fallo:

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml -e @ansible/secrets.yml
```

---

## FASE 4 — DNS de clientes externos

### INC-10: Los dominios `.ecocloud.local` no resuelven desde equipos cliente

**Causa raíz:**  
Los equipos cliente usan el servidor DNS del router, que desconoce los dominios
internos `.ecocloud.local`. AdGuard Home resuelve estos dominios dentro del clúster
pero los clientes externos no lo tienen configurado como DNS.

**Solución temporal** (por equipo, Windows — PowerShell como Administrador):
```powershell
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" `
  -Value "192.168.1.80 nubes.ecocloud.local"
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" `
  -Value "192.168.1.80 monitor.ecocloud.local"
```

**Solución definitiva** (configuración en el router):  
Configurar el router para delegar el dominio `ecocloud.local` al servidor DNS de
AdGuard Home (IP asignada por MetalLB, normalmente 192.168.1.80). El procedimiento
varía según el modelo de router.

---

## Comandos de diagnóstico rápido

```bash
# Estado general del clúster
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -A

# Logs de un servicio
sudo k3s kubectl logs deploy/lldap
sudo k3s kubectl logs deploy/nextcloud
sudo k3s kubectl logs deploy/ollama
sudo k3s kubectl logs deploy/middleware

# Describir un pod que no arranca (los Events son lo más útil)
sudo k3s kubectl describe pod -l app=lldap
sudo k3s kubectl describe pod -l app=nextcloud

# Ver IPs asignadas por MetalLB
sudo k3s kubectl get svc -A | grep LoadBalancer

# Estado de volúmenes Longhorn
sudo k3s kubectl get pvc -A
sudo k3s kubectl get pods -n longhorn-system

# Forzar eliminación de pods bloqueados
sudo k3s kubectl delete pod -l app=lldap
sudo k3s kubectl delete pod -l app=nextcloud

# Probar el middleware desde dentro del clúster
sudo k3s kubectl run curl-test --image=curlimages/curl:latest --rm -i --tty -- \
  curl -s -X POST http://middleware-svc:5000 \
  -H "Content-Type: application/json" \
  -d '{"prompt":"¿De qué color es el cielo?"}'
```
