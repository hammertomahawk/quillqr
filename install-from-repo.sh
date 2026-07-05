sudo systemctl stop quillqr

sudo rsync -a --delete \
  --chown=root:root \
  --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='instance/' \
  --exclude='tmp/' \
  --exclude='__pycache__/' \
  /home/tinkerton/repos/quillqr/ \
  /srv/quillqr/

sudo install -d -o svcweb01 -g svcweb01 -m 750 /srv/quillqr/instance
sudo install -d -o svcweb01 -g svcweb01 -m 750 /srv/quillqr/tmp

sudo systemctl start quillqr