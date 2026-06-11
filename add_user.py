"""
Utilitário para adicionar/atualizar usuários no users.json
Uso: python add_user.py
"""
import json, os, getpass
from werkzeug.security import generate_password_hash

USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")

try:
    with open(USERS_FILE) as f:
        users = json.load(f)
except FileNotFoundError:
    users = {}

print("=== Gerenciar Usuários do Dashboard ===")
print(f"Usuários existentes: {', '.join(users.keys()) or '(nenhum)'}\n")

username = input("Usuário (deixe vazio para cancelar): ").strip().lower()
if not username:
    print("Cancelado.")
    exit()

password = getpass.getpass("Senha: ")
confirm  = getpass.getpass("Confirme a senha: ")

if password != confirm:
    print("Senhas não conferem. Cancelado.")
    exit()

users[username] = {"password": generate_password_hash(password)}

with open(USERS_FILE, "w") as f:
    json.dump(users, f, indent=2)

print(f"\nUsuário '{username}' salvo com sucesso em users.json.")
print("Lembre de fazer deploy para que a mudança entre em vigor no Cloud Run.")
