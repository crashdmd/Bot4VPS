import paramiko
import os

def create_ssh_client(server):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    auth_type = server.get(
        "auth_type",
        "password"
    )

    if auth_type == "key":
        ssh.connect(
            hostname=server["host"],
            port=server.get("port", 22),
            username=server["user"],
            key_filename=server["key_path"],
            timeout=8
        )
    else:
        ssh.connect(
            hostname=server["host"],
            port=server.get("port", 22),
            username=server["user"],
            password=server["password"],
            timeout=8
        )

    return ssh

def get_available_keys():
    return [
        f
        for f in os.listdir("/opt/bot4vps/keys")
        if not f.endswith(".pub")
    ]

def test_connection(server):
    try:
        ssh = create_ssh_client(server)
        ssh.close()

        return True, "OK"

    except Exception as e:
        return False, str(e)