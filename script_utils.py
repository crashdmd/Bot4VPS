import os


def load_scripts():
    try:
        return sorted([
            f for f in os.listdir("scripts")
            if f.endswith(".sh")
        ])
    except Exception as e:
        print(
            f"load_scripts error: {e}",
            flush=True
        )
        return []


def get_script_info(script_name):
    path = f"scripts/{script_name}"

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = len(f.readlines())

        size = os.path.getsize(path)

        return {
            "size": size,
            "lines": lines
        }

    except Exception as e:
        print(
            f"get_script_info error: {e}",
            flush=True
        )

        return None


def read_script(script_name):
    path = f"scripts/{script_name}"

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    except Exception as e:
        print(
            f"read_script error: {e}",
            flush=True
        )

        return None


def get_script_params(script_name):
    content = read_script(script_name)
    if not content:
        return []

    params = []
    param_by_name = {}
    option_lines = []

    for line in content.splitlines():
        line = line.strip()

        if line.startswith("# BOT_PARAM "):
            parts = line.split()
            if len(parts) < 5:
                continue

            param = {
                "name": parts[2],
                "type": parts[3],
                "condition": None,
                "label": "",
                "options": []
            }

            start_label = 4
            if parts[4].startswith("if="):
                param["condition"] = parts[4][3:]
                start_label = 5

            param["label"] = " ".join(parts[start_label:])
            params.append(param)
            param_by_name[param["name"]] = param

        elif line.startswith("# BOT_OPTION "):
            parts = line.split(maxsplit=4)
            if len(parts) >= 5:
                option_lines.append(parts)

    # Обрабатываем BOT_OPTION только для параметров типа select
    for parts in option_lines:
        name = parts[2]
        value = parts[3]
        label = parts[4]

        param = param_by_name.get(name)
        if param and param["type"] == "select":
            param["options"].append({
                "value": value,
                "label": label
            })

    return params

async def delete_script(script_name):
    path = f"scripts/{script_name}"

    try:
        os.remove(path)
        return True, None

    except Exception as e:
        return False, str(e)
