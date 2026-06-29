p = "bot.py"

with open(p, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

new_lines = []

for i, line in enumerate(lines, start=1):
    if 471 <= i <= 484 and line.startswith("        "):
        line = line[4:]
    new_lines.append(line)

with open(p, "w", encoding="utf-8") as f:
    f.write("\n".join(new_lines) + "\n")

print("bot.py corregido")