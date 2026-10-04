import os
import glob

# Find all generated SVGs in dist/
svg_files = glob.glob('dist/*.svg')

# The CSS we want to inject to slow down the animation and add milestone color changes.
# The `snk` action typically uses <style> block and classes like `.snake` or `.snake__svg-path`.
# We'll target the elements generically and enforce the slower animation and color pulse.

css_injection = """
/* --- INJECTED: SLOWER ANIMATION & MILESTONE COLORS --- */
svg {
    --snake-duration: 20s; /* Much slower and fluid */
}

/* Override the default animation to be slower and add color changes */
path, rect {
    animation-duration: 20s !important; 
}

/* Target the snake specifically. Snk usually gives it a specific color in the inline style or class */
[fill="#7C3AED"], [stroke="#7C3AED"] {
    animation: snake-milestone-colors 20s infinite linear !important;
}

@keyframes snake-milestone-colors {
    0%   { fill: #7C3AED; stroke: #7C3AED; filter: drop-shadow(0 0 2px #7C3AED); } /* 0%   - Violet */
    25%  { fill: #3FB950; stroke: #3FB950; filter: drop-shadow(0 0 4px #3FB950); } /* 25%  - Green */
    50%  { fill: #D29922; stroke: #D29922; filter: drop-shadow(0 0 6px #D29922); } /* 50%  - Yellow */
    75%  { fill: #DB6D28; stroke: #DB6D28; filter: drop-shadow(0 0 8px #DB6D28); } /* 75%  - Orange */
    100% { fill: #F87171; stroke: #F87171; filter: drop-shadow(0 0 12px #F87171);} /* 100% - Red/Hot */
}
/* ---------------------------------------------------- */
"""

for file_path in svg_files:
    with open(file_path, 'r', encoding='utf-8') as f:
        svg_content = f.read()

    # Inject CSS before the closing </style> tag
    if '</style>' in svg_content:
        svg_content = svg_content.replace('</style>', css_injection + '\n</style>')
        print(f"Injected milestone CSS into {file_path}")
    
    # Also slow down the existing variables if they exist
    svg_content = svg_content.replace('5s', '20s').replace('3s', '20s')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(svg_content)

print("Snake post-processing complete.")
