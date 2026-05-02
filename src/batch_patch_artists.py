#!/usr/bin/env python3
"""Batch patch all ~/wiki/*.wiki files: replace bare Chinese-name artist links with piped syntax."""
import os
import re
import glob

WIKI_DIR = os.path.expanduser("~/wiki")

# Mapping: Chinese name -> English page name (as appears in wiki links)
ARTIST_MAP = {
    "列奥纳多·达·芬奇": "Leonardo_da_Vinci",
    "米开朗基罗": "Michelangelo",
    "拉斐尔": "Raphael",
    "卡拉瓦乔": "Caravaggio",
    "伦勃朗": "Rembrandt",
    "维米尔": "Johannes_Vermeer",
    "委拉斯开兹": "Diego_Velázquez",
    "贝尼尼": "Gian_Lorenzo_Bernini",
    "鲁本斯": "Peter_Paul_Rubens",
    "戈雅": "Francisco_Goya",
    "德拉克罗瓦": "Eugène_Delacroix",
    "透纳": "JMW_Turner",
    "弗里德里希": "Caspar_David_Friedrich",
    "库尔贝": "Gustave_Courbet",
    "马奈": "Édouard_Manet",
    "莫奈": "Claude_Monet",
    "雷诺阿": "Pierre-Auguste_Renoir",
    "德加": "Edgar_Degas",
    "梵高": "Vincent_van_Gogh",
    "马蒂斯": "Henri_Matisse",
    "蒙克": "Edvard_Munch",
    "毕加索": "Pablo_Picasso",
    "杜尚": "Marcel_Duchamp",
    "达利": "Salvador_Dalí",
    "波洛克": "Jackson_Pollock",
    "安迪·沃霍尔": "Andy_Warhol",
    "弗里达·卡洛": "Frida_Kahlo",
    "乔托": "Giotto",
    "多纳泰罗": "Donatello",
    "波提切利": "Sandro_Botticelli",
    "布鲁内莱斯基": "Filippo_Brunelleschi",
    "菲狄亚斯": "Phidias",
    "普拉克西特列斯": "Praxiteles",
    "提香": "Titian",
    "丢勒": "Albrecht_Dürer",
    "凡·艾克": "Jan_van_Eyck",
    "博斯": "Hieronymus_Bosch",
    "格列柯": "El_Greco",
}

# Build reverse map from English page to Chinese for context
EN_TO_CN = {v: k for k, v in ARTIST_MAP.items()}

def process_files():
    wiki_files = sorted(glob.glob(os.path.join(WIKI_DIR, "*.wiki")))
    total_files = len(wiki_files)
    total_replacements = 0
    per_mapping_counts = {cn: 0 for cn in ARTIST_MAP}
    files_modified = set()
    
    print(f"Processing {total_files} .wiki files in {WIKI_DIR}")
    print("=" * 70)
    
    for filepath in wiki_files:
        basename = os.path.basename(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        original = content
        file_changes = 0
        
        for cn_name, en_name in ARTIST_MAP.items():
            # Match [[ChineseName]] but NOT [[Something|ChineseName]]
            # Pattern: [[ followed by exactly the Chinese name, then ]]
            # Must not be preceded by | (i.e., not part of a pipe link)
            pattern = re.escape(f"[[{cn_name}]]")
            
            # Find all occurrences that are NOT preceded by |
            # We do this by finding positions and checking the char before
            new_content = content
            count = 0
            
            # Simpler approach: look for [[cn_name]] and verify no | before it
            idx = 0
            while True:
                pos = new_content.find(f"[[{cn_name}]]", idx)
                if pos == -1:
                    break
                # Check if preceded by | (pipe link target)
                if pos > 0 and new_content[pos - 1] == '|':
                    # This is [[English|Chinese]], skip
                    idx = pos + len(f"[[{cn_name}]]")
                    continue
                # It's a bare link, replace with [[English|Chinese]]
                replacement = f"[[{en_name}|{cn_name}]]"
                new_content = new_content[:pos] + replacement + new_content[pos + len(f"[[{cn_name}]]"):]
                count += 1
                idx = pos + len(replacement)
            
            per_mapping_counts[cn_name] += count
            
            content = new_content
        
        if content != original:
            files_modified.add(filepath)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            # Count total changes by diffing
            # But the per_mapping_counts already tracks this
    
    # Report
    print(f"\nFiles modified: {len(files_modified)}/{total_files}")
    print("=" * 70)
    print(f"{'Chinese Name':<20} {'English Page':<30} {'Replacements':>12}")
    print("-" * 70)
    
    grand_total = 0
    for cn_name in ARTIST_MAP:
        count = per_mapping_counts[cn_name]
        if count > 0:
            en_name = ARTIST_MAP[cn_name]
            print(f"{cn_name:<20} {en_name:<30} {count:>12}")
            grand_total += count
    
    print("-" * 70)
    print(f"{'TOTAL':<20} {'':<30} {grand_total:>12}")
    
    # List modified files
    if files_modified:
        print(f"\nModified files:")
        for f in sorted(files_modified):
            print(f"  {os.path.basename(f)}")

if __name__ == "__main__":
    process_files()
