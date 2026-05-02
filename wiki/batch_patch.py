import os
import re

wiki_dir = "/home/hrxia/wiki"
mappings = [
    ("样式主义", "Mannerism"),
    ("浪漫主义", "Romanticism"),
    ("新古典主义", "Neoclassicism"),
    ("印象派", "Impressionism"),
    ("后印象派", "Post-Impressionism"),
    ("立体主义", "Cubism"),
    ("超现实主义", "Surrealism"),
    ("野兽派", "Fauvism"),
    ("表现主义", "Expressionism"),
    ("未来主义", "Futurism"),
    ("抽象表现主义", "Abstract_expressionism"),
    ("波普艺术", "Pop_art"),
    ("哥特式艺术", "Gothic_art"),
    ("罗马式艺术", "Romanesque_art"),
    ("拜占庭艺术", "Byzantine_art"),
    ("古希腊艺术", "Ancient_Greek_art"),
    ("古罗马艺术", "Ancient_Roman_art"),
    ("古埃及艺术", "Ancient_Egyptian_art"),
    ("史前艺术", "Prehistoric_art"),
    ("北方文艺复兴", "Northern_Renaissance"),
    ("国际哥特式", "International_Gothic"),
    ("威尼斯画派", "Venetian_School"),
]

results = {}

for chinese, english in mappings:
    old = f"[[{chinese}]]"
    new = f"[[{english}|{chinese}]]"
    total_count = 0
    files_touched = []
    
    for fname in sorted(os.listdir(wiki_dir)):
        if not fname.endswith(".wiki"):
            continue
        fpath = os.path.join(wiki_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old)
        if count > 0:
            content = content.replace(old, new)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            total_count += count
            files_touched.append(fname)
    
    results[(chinese, english)] = total_count
    if total_count > 0:
        print(f"{chinese} -> {english}: {total_count} replacements in {len(files_touched)} files")
    else:
        print(f"{chinese} -> {english}: 0 replacements (not found)")

print("\n=== SUMMARY ===")
grand_total = sum(results.values())
print(f"Total replacements across all mappings: {grand_total}")
for (ch, en), cnt in results.items():
    print(f"  {ch} -> {en}: {cnt}")
