import os, shutil
os.makedirs("instance", exist_ok=True)
db_path = os.path.join("instance", "app.db")
if os.path.exists(db_path):
    os.remove(db_path)
print("Base reiniciada (instance/app.db eliminado si existía).")
