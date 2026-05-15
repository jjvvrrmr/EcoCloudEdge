# Troubleshooting — EcoCloud Edge

> Este documento recoge las incidencias reales encontradas durante el despliegue.
> Cada problema tiene diagnóstico, causa raíz y solución verificada.

---

## Hito 3 — LLDAP

### INC-01: CrashLoopBackOff por permisos en Longhorn

**Síntoma:**
```
lldap-xxx   0/1   CrashLoopBackOff   6 (2m15s ago)   8m
```

**Causa raíz:**  
Longhorn provisiona el PVC con permisos `root`. La imagen oficial de LLDAP
ejecuta el proceso como `UID 1000` y no puede escribir en `/data` para crear
su base de datos SQLite.

**Solución:**  
Añadir `securityContext.fsGroup: 1000` al spec del pod:
```yaml
spec:
  securityContext:
    fsGroup: 1000
```

---

### INC-02: Panic en Rust — variable LLDAP_LDAP_USER_PASS no documentada

**Síntoma en logs:**
```
thread 'main' panicked at server/src/main.rs:54:10:
The LDAP admin password must be initialized. Either set the `ldap_user_pass`
config value or the `LLDAP_LDAP_USER_PASS` environment variable.
```

**Causa raíz:**  
LLDAP v0.6.x hace obligatoria la variable `LLDAP_LDAP_USER_PASS` pero no lo
documenta en la guía de inicio rápido.

**Solución:**  
Añadir la variable al Deployment:
```yaml
- name: LLDAP_LDAP_USER_PASS
  value: "tu-contraseña-admin"
```

---

### INC-03: ContainerCreating indefinido — interbloqueo RWO con RollingUpdate

**Síntoma:**
```
lldap-nuevo  0/1   ContainerCreating   0   99s   # bloqueado
lldap-viejo  0/1   CrashLoopBackOff    6   11m   # sigue girando
```

**Causa raíz:**  
La estrategia `RollingUpdate` (defecto) intenta levantar el pod nuevo antes de
destruir el antiguo. El volumen Longhorn es `ReadWriteOnce` → el pod antiguo
mantiene el bloqueo exclusivo → el nuevo no puede montar el disco.

**Solución:**
```yaml
spec:
  strategy:
    type: Recreate
```
Si el interbloqueo ya está activo, forzar limpieza:
```bash
sudo k3s kubectl delete pod -l app=lldap
```

---

## Hito 3 — Red y balanceo de carga

### INC-04: LoadBalancer de AdGuard en `<pending>` indefinido

**Síntoma:**
```
adguard-svc   LoadBalancer   10.43.77.33   <pending>   ...
```

**Causa raíz:**  
k3s instalado con `--disable servicelb` no incluye el controlador Klipper.
Sin controlador de LoadBalancer, los servicios de tipo `LoadBalancer` nunca
reciben IP externa en entornos bare-metal.

**Solución:**  
Desplegar MetalLB v0.14.3:
```bash
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.3/config/manifests/metallb-native.yaml
kubectl wait --namespace metallb-system --for=condition=ready pod --selector=app=metallb --timeout=120s
kubectl apply -f manifests/04-metallb/metallb-pool.yaml
```

---

### INC-05: `kubectl get svc -l "app in (lldap, adguard)"` devuelve vacío

**Causa raíz:**  
Los manifiestos incluían `selector.app` (para apuntar a los pods) pero
omitían `metadata.labels` en el propio objeto `Service`. El filtro de labels
busca en los metadatos del Service, no en el selector.

**Solución:**  
Añadir el bloque `labels` a los metadatos del Service:
```yaml
metadata:
  name: lldap-svc
  labels:
    app: lldap   # <-- esto faltaba
```

---

## Hito 2 — Longhorn

### INC-06: Degradación general del clúster por saturación de red

**Síntoma:**  
Latencia alta en todos los servicios. Longhorn creando 3 réplicas por volumen
en una red de 100 Mbps.

**Solución:**  
Aplicar ConfigMap **antes** de desplegar Longhorn:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: longhorn-default-setting
  namespace: longhorn-system
data:
  default-setting.yaml: |-
    default-replica-count: 2
```

---

## Hito 5 — Ollama

### INC-07: OOM Kill del pod de Ollama con modelos estándar

**Síntoma:**  
El pod de Ollama muere inmediatamente. `dmesg` muestra `oom-kill`.

**Causa raíz:**  
Cada nodo tiene 4 GB de RAM. Tras SO + infraestructura k3s + Longhorn,
quedan ~1.5 GB disponibles. Un modelo 7B en FP16 requiere ~14 GB.

**Solución:**  
Usar modelos cuantizados GGUF y añadir límite de memoria:
```bash
ollama pull tinyllama     # ~670 MB
ollama pull qwen2:0.5b    # ~400 MB
```
```yaml
resources:
  limits:
    memory: "2Gi"
```

---

## Hito 4 — DNS de clientes externos

### INC-08: Los dominios `.ecocloud.local` no resuelven desde equipos cliente

**Causa raíz:**  
Los clientes usan el DNS del router, que desconoce los dominios internos
`.ecocloud.local`. AdGuard Home solo resuelve dentro del clúster.

**Solución temporal** (por equipo):
```powershell
# Windows — PowerShell como Administrador
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" `
  -Value "192.168.1.81 nubes.ecocloud.local"
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" `
  -Value "192.168.1.81 monitor.ecocloud.local"
```

**Solución definitiva** (router):  
Configurar el router para delegar el dominio `ecocloud.local` al servidor
DNS de AdGuard (192.168.1.80).

---

## Comandos de diagnóstico rápido

```bash
# Estado general del clúster
sudo k3s kubectl get nodes
sudo k3s kubectl get pods -A

# Logs de un servicio específico
sudo k3s kubectl logs deploy/lldap
sudo k3s kubectl logs deploy/nextcloud
sudo k3s kubectl logs deploy/ollama

# Describir un pod que no arranca
sudo k3s kubectl describe pod -l app=lldap

# Ver IPs asignadas por MetalLB
sudo k3s kubectl get svc -A | grep LoadBalancer

# Estado de volúmenes Longhorn
sudo k3s kubectl get pvc -A
sudo k3s kubectl get pods -n longhorn-system
```
