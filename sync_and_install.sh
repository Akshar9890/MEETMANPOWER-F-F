#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

docker --context colima-ff-sprint3 exec docker-frappe-1 rm -rf /home/frappe/frappe-bench/apps/kesari_jefs

COPYFILE_DISABLE=1 tar --no-mac-metadata --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='._*' -cf - kesari_jefs \
  | docker --context colima-ff-sprint3 exec -i docker-frappe-1 tar -xf - -C /home/frappe/frappe-bench/apps

docker --context colima-ff-sprint3 exec docker-frappe-1 bash -lc '
set -e
export PATH="${NVM_DIR}/versions/node/v${NODE_VERSION_DEVELOP}/bin/:${PATH}"
cd /home/frappe/frappe-bench
uv pip install --quiet --no-deps -e /home/frappe/frappe-bench/apps/kesari_jefs --python /home/frappe/frappe-bench/env/bin/python
python3 - <<PY
p = "sites/apps.txt"
apps = ["frappe", "hrms", "erpnext", "kesari_jefs"]
open(p, "w").write("\n".join(apps) + "\n")
PY
ln -sfn /home/frappe/frappe-bench/apps/kesari_jefs/kesari_jefs/public /home/frappe/frappe-bench/sites/assets/kesari_jefs
if ! bench --site hrms.localhost list-apps | grep -q "kesari_jefs"; then
  bench --site hrms.localhost install-app kesari_jefs
else
  bench --site hrms.localhost migrate
fi
bench --site hrms.localhost clear-cache
'
docker --context colima-ff-sprint3 compose -f "hrms/docker/docker-compose.yml" restart frappe
