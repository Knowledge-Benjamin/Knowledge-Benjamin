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
    --snake-duration: 120s; /* Much slower and fluid */
}

/* Target the specific classes Platane/snk uses for the grid and snake */
.s, .u, .c {
    animation-duration: 120s !important; 
}

/* Target the snake specifically. Snk usually gives it a specific color in the inline style or class */
[fill="#7C3AED"], [stroke="#7C3AED"], .s {
    animation: snake-milestone-colors 120s infinite linear !important;
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

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(svg_content)

print("Snake post-processing complete.")
