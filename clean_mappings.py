#!/usr/bin/env python3
import json
import os

mapping_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'monitoring_server_mappings.json')

if os.path.exists(mapping_file):
    with open(mapping_file, 'r') as f:
        mappings = json.load(f)
    
    print("Before cleanup:")
    for cat, servers in mappings.items():
        print(f"  {cat}: {servers}")
    
    # Hapus server dari kategori selain 'prioritas'
    for cat in list(mappings.keys()):
        if cat != 'prioritas':
            mappings[cat] = []
    
    print("\nAfter cleanup:")
    for cat, servers in mappings.items():
        print(f"  {cat}: {servers}")
    
    with open(mapping_file, 'w') as f:
        json.dump(mappings, f, indent=2)
    
    print("\nMapping file cleaned!")
else:
    print("Mapping file not found!")
