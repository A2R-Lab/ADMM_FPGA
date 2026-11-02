#!/usr/bin/env python3
"""Prepare isolated HLS experiments from the production solver; run on build host.

Promising profiles from this campaign:
  split_fused0: fused stage updates, bank factor 4, exact split row feedback.
  split_far3:   bank factor 2, registered rho, pipelined stage multipliers, and
                three-stage multipliers for older-row substitution products.

Both use a 100 MHz HLS schedule with zero HLS clock uncertainty. Operating clock
must be validated by routed timing; a successful HLS run alone is not sufficient.
The experiment retains the 32/10 fixed-point format, original acc_t rounding,
coefficient arrays, finite-horizon factorization, and ten ADMM iterations.

Example after activating ~/venv and sourcing the AMD 2025.2 settings:
  python prepare.py --output /path/to/fresh/h10 --horizon 10 --variants baseline split_far3
  python run.py /path/to/fresh/h10 baseline split_far3
  python route.py /path/to/fresh/h10 split_far3

Source and configuration are emitted in each variant directory. The original
solver remains the reference input to the experiment generator.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def replace_region(text, start, end, replacement):
    a = text.index(start)
    b = text.index(end, a)
    return text[:a] + replacement + text[b:]


def explicit_stage(text, header):
    def array(name):
        body = re.search(r'const \w+ ' + name + r'\[.*?= \{(.*?)\n\};', header, re.S)[1]
        rows = re.findall(r'\{([^{}]*)\}', body)
        def vals(s):
            return [float(v) for v in re.findall(r'\)\s*([-+\d.eE]+)', s)]
        return [vals(r) for r in rows] if rows else vals(body)

    counts = array('A_stage_row_counts')
    cols = array('A_stage_row_cols')
    values = array('A_stage_row_vals')
    tc = array('A_stage_col_counts')
    tr = array('A_stage_col_rows')
    tv = array('A_stage_col_vals')
    B = array('B_stage')
    # Keep the original fp_t coefficient conversions and sequential acc_t assignments.
    dyn = []
    for r in range(12):
        dyn += ['        {', f'        acc_t a = (acc_t)xkp1[{r}];']
        for j in range(int(counts[r])):
            if values[r][j] != 0:
                dyn += [f'        a -= (acc_t)A_stage_row_vals[{r}][{j}] * (acc_t)xk[{int(cols[r][j])}];']
        for c in range(4):
            if B[r][c] != 0:
                dyn += [f'        a -= (acc_t)B_stage[{r}][{c}] * (acc_t)uk[{c}];']
        dyn += [f'        const int i = row_base + {r};',
                '        const fp_t Axi = (fp_t)a;',
                '        const fp_t yi = y[i] + Axi;',
                '        y[i] = yi;', '        b_tmp[i] = rho_mul(-yi, false);', '        }']
    text = replace_region(text, '        ADMM_IT_DYN_ROW_LOOP:', '\n    ADMM_IT_U_INEQ_STAGE_LOOP:', '\n'.join(dyn) + '\n    }\n')
    at = []
    for i in range(12):
        at += ['        {', f'        acc_t a = is_first_stage ? (acc_t)x[{i}] : (acc_t)prev_row_vals[{i}];']
        for j in range(int(tc[i])):
            if tv[i][j] != 0:
                at += [f'        a -= (acc_t)A_stage_col_vals[{i}][{j}] * (acc_t)row_vals[{int(tr[i][j])}];']
        at += [f'        ATx[xk_col + {i}] = (fp_t)a;', f'        prev_row_vals[{i}] = row_vals[{i}];', '        }']
    for i in range(4):
        at += ['        {', '        acc_t a = 0;']
        for r in range(12):
            if B[r][i] != 0:
                at += [f'        a -= (acc_t)B_stage[{r}][{i}] * (acc_t)row_vals[{r}];']
        at += [f'        ATx[uk_col + {i}] = (fp_t)a;', '        }']
    return replace_region(text, '        AT_MUL_DYN_WRITE_XK:', '\n    AT_MUL_DYN_FINAL_XN:', '\n'.join(at) + '\n    }\n')


def bank(text, factor):
    # Partition the physical owners, not just local stage buffers.
    for decl, name in [('static fp_t x[N_VAR] = {0};', 'x'),
                       ('static fp_t b[N_VAR] = {0};', 'b'),
                       ('static fp_t y[N_CONSTR] = {0};', 'y'),
                       ('fp_t tmp[N_VAR];', 'tmp'), ('fp_t b_tmp[N_CONSTR];', 'b_tmp')]:
        text = text.replace(decl, decl + f'\n#pragma HLS ARRAY_PARTITION variable={name} cyclic factor={factor} dim=1')
    return text


def substitution(text, factor):
    for name in ['L_banded', 'LT_banded']:
        marker = '    fp_t window[' + ('L_BANDED_COLS' if name == 'L_banded' else 'LT_BANDED_COLS')
        text = text.replace(marker, f'#pragma HLS ARRAY_PARTITION variable={name} cyclic factor={factor} dim=2\n' + marker)
    for label in ['FORW_SUBST_DOT_PRODUCT_LOOP', 'DOT_PRODUCT', 'FORW_SUBST_SHIFT_REGISTER_LOOP', 'SHIFT_WINDOW', 'INIT_WINDOW']:
        pattern = r'(' + label + r':\s*for\s*\([^\n]*\)\s*\{)'
        directive = f'\n#pragma HLS UNROLL factor={factor}' if label in ['DOT_PRODUCT', 'FORW_SUBST_DOT_PRODUCT_LOOP'] else '\n#pragma HLS UNROLL'
        text, n = re.subn(pattern, r'\g<1>' + directive, text)
        assert n == 1, (label, n)
    for label in ['FORW_SUBST_EXTERN_LOOP', 'BACK_SUBST_EXTERN_LOOP']:
        text = re.sub(r'(' + label + r':\s*for\s*\([^\n]*\)\s*\{)', r'\g<1>\n#pragma HLS PIPELINE', text)
    return text


def fused_update(text):
    """Fuse staged constraint/dual updates into AT; preserve every fp_t boundary."""
    at = text[text.index('    fp_t prev_row_vals[STATE_SIZE]'):text.index('\n#else\n    AT_MUL_EXTERN_LOOP:')]
    at_start = '        AT_MUL_DYN_WRITE_XK:' if '        AT_MUL_DYN_WRITE_XK:' in at else '        {'
    at_body = at[at.index(at_start):at.index('\n    AT_MUL_DYN_FINAL_XN:')]
    # Strip the closing horizon-loop brace, retaining explicit component scopes.
    at_body = at_body.rsplit('\n    }', 1)[0]
    at_body = at_body.replace('ATx[', 'b[').replace('(acc_t)x[', '(acc_t)b_tmp[')
    start = text.index('    fp_t tmp[N_VAR];', text.index('void ADMM_iteration('))
    end = text.index('\n#else', start)
    old = text[start:end]
    prefix = old[:old.index('    ADMM_IT_DYN_STAGE_LOOP:')]
    prefix = prefix.replace('fp_t b_tmp[N_CONSTR];', 'fp_t b_tmp[STATE_SIZE];')
    prefix += '    fp_t prev_row_vals[STATE_SIZE] = {0};\n#pragma HLS ARRAY_PARTITION variable=prev_row_vals complete dim=1\n'
    dyn = old[old.index('    ADMM_IT_DYN_STAGE_LOOP:'):old.index('\n    ADMM_IT_U_INEQ_STAGE_LOOP:')]
    dyn = dyn.rsplit('\n    }', 1)[0]
    dyn = dyn.replace('        fp_t xk[STATE_SIZE];', '        fp_t row_vals[STATE_SIZE];\n#pragma HLS ARRAY_PARTITION variable=row_vals complete dim=1\n        const bool is_first_stage = (k == 0);\n        fp_t xk[STATE_SIZE];')
    # Each generated row has a literal offset and the same original y update.
    if 'ADMM_IT_DYN_ROW_LOOP:' in dyn:
        dyn = dyn.replace('b_tmp[i] = rho_mul(-yi, false);', 'row_vals[r] = rho_mul(-yi, false);')
    else:
        for r in range(12):
            marker = f'const int i = row_base + {r};'
            a = dyn.index(marker)
            b = dyn.index('b_tmp[i] = rho_mul(-yi, false);', a)
            dyn = dyn[:b] + dyn[b:].replace('b_tmp[i] = rho_mul(-yi, false);', f'row_vals[{r}] = rho_mul(-yi, false);', 1)
    u_update = '''
        FUSED_U_LOOP: for (int u = 0; u < INPUT_SIZE; ++u) {
            const int i = START_U_INEQ + k * INPUT_SIZE + u;
            const fp_t Axi = uk[u];
            fp_t zi = Axi + y[i];
            if (zi < (fp_t)U_MIN) zi = (fp_t)U_MIN;
            else if (zi > (fp_t)U_MAX) zi = (fp_t)U_MAX;
            const fp_t yi = y[i] + (Axi - zi);
            y[i] = yi;
            const fp_t contribution = rho_mul(zi - yi, true);
            b[uk_col + u] += contribution;
        }
'''
    xy_update = '''
        FUSED_XY_LOOP: for (int axis = 0; axis < 2; ++axis) {
            const int i = START_XY_INEQ + (stage - 1) * 2 + axis;
            const fp_t Axi = x[stage * STAGE_SIZE + axis];
            fp_t zi = Axi + y[i];
            const bool dynamic = use_dynamic_constraint_stage(stage, axis);
            const fp_t lo = dynamic ? dynamic_min : (fp_t)XY_MIN;
            const fp_t hi = dynamic ? dynamic_max : (fp_t)XY_MAX;
            if (zi < lo) zi = lo;
            else if (zi > hi) zi = hi;
            const fp_t yi = y[i] + (Axi - zi);
            y[i] = yi;
            const fp_t contribution = rho_mul(zi - yi, true);
            b[stage * STAGE_SIZE + axis] += contribution;
        }
'''
    new = prefix + dyn + '\n' + at_body + u_update
    new += '        if (k > 0) {\n            const int stage = k;\n' + xy_update + '        }\n    }\n'
    new += '    for (int i = 0; i < STATE_SIZE; ++i) b[HORIZON_LENGTH * STAGE_SIZE + i] = prev_row_vals[i];\n'
    new += '    { const int stage = HORIZON_LENGTH;\n' + xy_update.replace('FUSED_XY_LOOP:', 'FUSED_FINAL_XY_LOOP:') + '    }\n'
    return text[:start] + new + text[end:]


def sparse_substitution(text, header):
    # Specialize each within-stage row pattern, retaining all stage-dependent values.
    for matrix, start, end, forward in [
        ('L_banded', '        FORW_SUBST_DOT_PRODUCT_LOOP:', '\n        acc_t new_x', True),
        ('LT_banded', '        DOT_PRODUCT:', '\n        acc_t new_x', False),
    ]:
        body = re.search(r'const fp_t ' + matrix + r'\[.*?= \{(.*?)\n\};', header, re.S)[1]
        rows = [[float(v) for v in re.findall(r'\)\s*([-+\d.eE]+)', r)] for r in re.findall(r'\{([^{}]*)\}', body)]
        width = len(rows[0])
        code = ['        static_assert(STAGE_SIZE == 16, "stage specialization requires 16 components");', '        switch (i & 15) {']
        for phase in range(16):
            code += [f'        case {phase}: {{']
            for j in (range(width - 1) if forward else range(width - 2, -1, -1)):
                col = j if forward else j + 1
                if any(row[col] != 0 for row in rows[phase::16]):
                    expr = f'(acc_t){matrix}[i][{col}] * (acc_t)window[{j}]'
                    if forward:
                        code += [f'            {{ acc_t term = {expr}; sum_val += term; }}']
                    else:
                        code += [f'            sum_val += {expr};']
            code += ['            break;', '        }']
        code += ['        }\n']
        text = replace_region(text, start, end, '\n'.join(code))
    return text


def blocked_substitution(text, header, block_size):
    """Unroll a block of ordered rows, exposing independent work to HLS late passes."""
    for matrix, label, forward in [('L_banded', 'FORW_SUBST_EXTERN_LOOP', True),
                                    ('LT_banded', 'BACK_SUBST_EXTERN_LOOP', False)]:
        body = re.search(r'const fp_t ' + matrix + r'\[.*?= \{(.*?)\n\};', header, re.S)[1]
        rows = [[float(v) for v in re.findall(r'\)\s*([-+\d.eE]+)', r)] for r in re.findall(r'\{([^{}]*)\}', body)]
        width = len(rows[0])
        masks = [[any(row[j if forward else j+1] != 0 for row in rows[lane::block_size])
                  for j in range(width-1)] for lane in range(block_size)]
        start = text.index('    ' + label + ':')
        opening = text.index('{', start)
        depth = 1
        close = opening + 1
        while depth:
            depth += (text[close] == '{') - (text[close] == '}')
            close += 1
        old_body = text[opening + 1:close - 1]
        dot_label = 'FORW_SUBST_DOT_PRODUCT_LOOP' if forward else 'DOT_PRODUCT'
        old_body = re.sub(r'(' + dot_label + r':\s*for\s*\([^\n]*\)\s*\{)',
                          r'\g<1>\n#pragma HLS UNROLL\n            if (active[lane][j]) {', old_body)
        # Close the mask condition at the original dot-product loop end.
        marker = '\n        acc_t new_x'
        idx = old_body.index(marker)
        old_body = old_body[:idx] + '        }\n' + old_body[idx:]
        init = f'    const bool active[{block_size}][{width-1}] = {{\n'
        init += ',\n'.join('        {' + ','.join('true' if v else 'false' for v in row) + '}' for row in masks)
        init += '\n    };\n#pragma HLS ARRAY_PARTITION variable=active complete dim=0\n'
        if forward:
            outer = f'for (int block = 0; block < (N_VAR + {block_size-1}) / {block_size}; ++block)'
            inner = f'for (int lane = 0; lane < {block_size}; ++lane)'
        else:
            outer = f'for (int block = (N_VAR - 1) / {block_size}; block >= 0; --block)'
            inner = f'for (int lane = {block_size-1}; lane >= 0; --lane)'
        code = init + f'    {label}_BLOCK:\n    {outer} {{\n#pragma HLS PIPELINE\n        {inner} {{\n#pragma HLS UNROLL\n'
        code += f'            const int i = block * {block_size} + lane;\n            if (i < N_VAR) {{\n' + old_body + '\n            }\n        }\n    }'
        text = text[:start] + code + text[close:]
    return text


def raw_feedback(text, bind=False, split=False):
    # Exact AP_RND/AP_SAT conversion: both acc_t and fp_t have 22 fractional bits.
    # Therefore saturating first to 40 bits and then to 32 is identical to one
    # 32-bit saturation. AP_RND is floor((raw_product + 2**21) / 2**22).
    # The split version computes (b-q)*diag + rounding_offset independently of
    # sum*diag; 74-bit integer arithmetic preserves the exact product and all
    # cancellation. rhs_product needs 65 bits, feedback_product needs 72 bits.
    # Only the final right shift and clamp quantize the result.
    helper = '''
static fp_t row_feedback(fp_t b, fp_t q, acc_t sum, fp_t diagonal) {
#pragma HLS INLINE
    static_assert(fp_t::width == 32 && fp_t::iwidth == 10, "fixed format");
    static_assert(acc_t::width == 40 && acc_t::iwidth == 18, "accumulator format");
    const ap_int<32> br = b.range(31, 0);
    const ap_int<32> qr = q.range(31, 0);
    const ap_int<40> sr = sum.range(39, 0);
    const ap_int<32> dr = diagonal.range(31, 0);
    const ap_int<42> residual = (ap_int<42>)br - (ap_int<42>)qr - (ap_int<42>)sr;
    ap_int<74> product = residual * dr;
    BIND_MARKER
    const ap_int<74> rounded = product + (ap_int<74>(1) << 21);
    const ap_int<52> scaled = rounded >> 22;
    ap_int<32> bits;
    if (scaled > ap_int<52>(2147483647LL)) bits = 2147483647;
    else if (scaled < ap_int<52>(-2147483648LL)) bits = ap_int<32>(-2147483648LL);
    else bits = scaled;
    fp_t result;
    result.range(31, 0) = bits.range(31, 0);
    return result;
}
'''.replace('    BIND_MARKER', '#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=1' if bind else '')
    if split:
        a = helper.index('    const ap_int<42> residual')
        b = helper.index('    const ap_int<52> scaled', a)
        helper = helper[:a] + '''    const ap_int<33> rhs = (ap_int<33>)br - (ap_int<33>)qr;
    const ap_int<65> rhs_product = rhs * dr;
    const ap_int<74> rhs_rounded = (ap_int<74>)rhs_product + (ap_int<74>(1) << 21);
    const ap_int<72> feedback_product = sr * dr;
    const ap_int<74> rounded = rhs_rounded - (ap_int<74>)feedback_product;
''' + helper[b:]
    marker = 'typedef typename AccType<fp_t>::type acc_t;'
    text = text.replace(marker, marker + '\n' + helper)
    text = text.replace('acc_t new_x = ((acc_t)b[i] - (acc_t)q_i - sum_val) * (acc_t)L_banded[i][L_BANDED_COLS - 1];',
                        'fp_t new_x = row_feedback(b[i], q_i, sum_val, L_banded[i][L_BANDED_COLS - 1]);')
    text = text.replace('acc_t new_x = ((acc_t)b[i] - sum_val) * (acc_t)LT_banded[i][0];',
                        'fp_t new_x = row_feedback(b[i], (fp_t)0, sum_val, LT_banded[i][0]);')
    return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--horizon', type=int, default=10)
    p.add_argument('--variants', nargs='+', default=['baseline', 'explicit', 'bank4', 'subst4'])
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    gen = root / 'generator'
    shutil.copytree(repo / 'scripts', gen / 'scripts', dirs_exist_ok=True)
    src = gen / 'vitis_projects/ADMM'
    src.mkdir(parents=True, exist_ok=True)
    (gen / 'vivado_project/vivado_project.srcs/sources_1/new').mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ADMM_HORIZON_LENGTH=str(args.horizon), ADMM_ITERATIONS='10',
               ADMM_ENABLE_TRAJECTORY='0', ADMM_SOLVER_ARCH='staged_a', ADMM_USE_FLOAT='0')
    with (root / 'generate.log').open('w') as log:
        subprocess.run([sys.executable, str(gen / 'scripts/header_generator.py')], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    original = Path(__file__).with_name('reference_ADMM.cpp').read_text()
    header = (src / 'data.h').read_text()
    for variant in args.variants:
        requested_variant = variant
        if variant in ['split_rho2', 'split_rhospec', 'split_pipeops', 'split_stage_regs', 'split_dot1', 'split_dot2', 'split_dot3', 'split_far2', 'split_far3']:
            variant = 'split_bank2'
        dest = root / requested_variant
        dest.mkdir(exist_ok=False)
        for f in ['ADMM.h', 'data_types.h']:
            shutil.copy2(repo / 'vitis_projects/ADMM' / f, dest / f)
        for f in ['data.h', 'admm_runtime_config.h']:
            shutil.copy2(src / f, dest / f)
        code = original
        if variant in ['explicit', 'bank4', 'combined4', 'bank16', 'fused', 'fused4', 'literal']:
            code = explicit_stage(code, header)
        if variant in ['fused', 'fused4', 'fused_loop', 'fused_loop_bank', 'fused_pipe', 'fused_unc1', 'fused_unc0', 'split_fused1', 'split_fused0', 'split_small0', 'split_bank2', 'split_rom2']:
            code = fused_update(code)
        if variant in ['bank4', 'combined4', 'bank16', 'fused4']:
            code = bank(code, 16 if variant == 'bank16' else 4)
        if variant in ['subst4', 'combined4']:
            code = substitution(code, 4)
        if variant == 'subst2':
            code = substitution(code, 2)
        if variant == 'sparse_subst':
            code = sparse_substitution(code, header)
        if variant in ['block4', 'block16']:
            code = blocked_substitution(code, header, int(variant[5:]))
        if variant in ['narrow', 'narrow_bank', 'narrow_sched', 'mul1', 'mul2']:
            assert code.count('acc_t new_x =') == 2
            code = code.replace('acc_t new_x =', 'fp_t new_x =')
        if variant in ['bank_only', 'narrow_bank']:
            code = bank(code, 4)
        if variant in ['stage_pipe_bank', 'fused_loop_bank', 'fused_pipe', 'fused_unc1', 'fused_unc0', 'split_fused1', 'split_fused0']:
            code = bank(code, 4)
        if variant in ['split_bank2', 'split_rom2']:
            code = bank(code, 2)
        if variant in ['stage_pipe', 'stage_pipe_bank', 'fused_pipe', 'fused_unc1', 'fused_unc0', 'split_fused1', 'split_fused0', 'split_small0', 'split_bank2', 'split_rom2']:
            code = re.sub(r'(ADMM_IT_DYN_STAGE_LOOP:\s*for\s*\([^\n]*\)\s*\{)',
                          r'\g<1>\n#pragma HLS PIPELINE', code)
        if variant == 'narrow_sched':
            code = substitution(code, 4)
        if variant in ['mul1', 'mul2']:
            latency = int(variant[-1])
            code = re.sub(r'        fp_t new_x = (.*);',
                lambda m: '        auto new_x_product = ' + m[1] + ';\n'
                + f'#pragma HLS BIND_OP variable=new_x_product op=mul impl=dsp latency={latency}\n'
                + '        fp_t new_x = new_x_product;', code)
        if variant == 'literal':
            for matrix in ['A_stage_row_vals', 'A_stage_col_vals', 'B_stage']:
                body = re.search(r'const fp_t ' + matrix + r'\[.*?= \{(.*?)\n\};', header, re.S)[1]
                rows = [re.findall(r'\)\s*([-+\d.eE]+)', r) for r in re.findall(r'\{([^{}]*)\}', body)]
                code = re.sub(matrix + r'\[(\d+)\]\[(\d+)\]', lambda m: '(fp_t)(' + rows[int(m[1])][int(m[2])] + ')', code)
        if variant in ['raw', 'raw_bind']:
            code = raw_feedback(code, variant == 'raw_bind')
        if variant in ['split', 'split_fused1', 'split_fused0', 'split_small0', 'split_bank2', 'split_rom2']:
            code = raw_feedback(code, split=True)
        if variant == 'split_rom2':
            for matrix, width in [('L_banded', 'L_BANDED_COLS'), ('LT_banded', 'LT_BANDED_COLS')]:
                marker = f'    fp_t window[{width}'
                code = code.replace(marker, f'#pragma HLS BIND_STORAGE variable={matrix} type=rom_1p impl=bram latency=2\n' + marker)
        if requested_variant in ['split_rho2', 'split_pipeops', 'split_stage_regs', 'split_dot1', 'split_dot2', 'split_dot3', 'split_far2', 'split_far3']:
            code = code.replace('static inline fp_t rho_mul(fp_t v, bool use_ineq_rho) {',
                'static inline fp_t rho_mul(fp_t v, bool use_ineq_rho) {\n#pragma HLS INLINE off\n#pragma HLS PIPELINE II=1\n#pragma HLS LATENCY min=2 max=2')
        if requested_variant == 'split_rhospec':
            marker = 'static inline fp_t rho_mul(fp_t v, bool use_ineq_rho) {'
            template = '''template<bool Inequality>
static fp_t rho_mul_static(fp_t v) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=2 max=2
    return Inequality ? rho_mul_ineq(v) : rho_mul_eq(v);
}

'''
            code = code.replace(marker, template + marker)
            code = re.sub(r'rho_mul\(([^,\n]+), (true|false)\)', r'rho_mul_static<\2>(\1)', code)
        if requested_variant in ['split_pipeops', 'split_dot1', 'split_dot2', 'split_dot3', 'split_far2', 'split_far3']:
            code = re.sub(r'(?m)^(\s*)(Axi_acc|acc_xk|acc_uk) -= ([^;\n]+ \* [^;\n]+);',
                          lambda m: m[1] + 'auto stage_product = ' + m[3] + ';\n'
                          + '#pragma HLS BIND_OP variable=stage_product op=mul impl=dsp latency=3\n'
                          + m[1] + m[2] + ' -= stage_product;', code)
        if requested_variant in ['split_dot1', 'split_dot2', 'split_dot3']:
            latency = int(requested_variant[-1])
            code = code.replace('acc_t mul_term = (acc_t)L_banded[i][j] * (acc_t)window[j];',
                'auto dot_product = (acc_t)L_banded[i][j] * (acc_t)window[j];\n'
                + f'#pragma HLS BIND_OP variable=dot_product op=mul impl=dsp latency={latency}\n'
                + '            acc_t mul_term = dot_product;')
            code = code.replace('sum_val += (acc_t)LT_banded[i][j + 1] * (acc_t)window[j];',
                'auto dot_product = (acc_t)LT_banded[i][j + 1] * (acc_t)window[j];\n'
                + f'#pragma HLS BIND_OP variable=dot_product op=mul impl=dsp latency={latency}\n'
                + '            sum_val += dot_product;')
        if requested_variant in ['split_far2', 'split_far3']:
            latency = int(requested_variant[-1])
            old = 'acc_t mul_term = (acc_t)L_banded[i][j] * (acc_t)window[j];\n            sum_val += mul_term;'
            new = 'if (j < L_BANDED_COLS - 2) {\n'
            new += '                auto far_product = (acc_t)L_banded[i][j] * (acc_t)window[j];\n'
            new += f'#pragma HLS BIND_OP variable=far_product op=mul impl=dsp latency={latency}\n'
            new += '                acc_t mul_term = far_product;\n                sum_val += mul_term;\n            } else {\n                '+old+'\n            }'
            assert old in code
            code = code.replace(old, new)
            old = 'sum_val += (acc_t)LT_banded[i][j + 1] * (acc_t)window[j];'
            new = 'if (j > 0) {\n'
            new += '                auto far_product = (acc_t)LT_banded[i][j + 1] * (acc_t)window[j];\n'
            new += f'#pragma HLS BIND_OP variable=far_product op=mul impl=dsp latency={latency}\n'
            new += '                sum_val += far_product;\n            } else {\n                '+old+'\n            }'
            assert old in code
            code = code.replace(old, new)
        if requested_variant == 'split_stage_regs':
            helper = '''static fp_t stage_dual_add(fp_t y, fp_t ax) {
#pragma HLS INLINE off
#pragma HLS PIPELINE II=1
#pragma HLS LATENCY min=2 max=2
    return y + ax;
}

'''
            code = code.replace('void ADMM_iteration(', helper + 'void ADMM_iteration(', 1)
            code = code.replace('const fp_t yi = y[i] + Axi;', 'const fp_t yi = stage_dual_add(y[i], Axi);')
        (dest / 'ADMM.cpp').write_text(code)
        cfg = 'part=xc7a100t-csg324-1\n[hls]\nflow_target=vivado\nsyn.top=ADMM_solver\nclock=10ns\nsyn.file=ADMM.cpp\n'
        if variant in ['unc0', 'unc1', 'fused_unc0', 'fused_unc1', 'split_fused1', 'split_fused0', 'split_small0']:
            cfg += f'clock_uncertainty={variant[-1]}ns\n'
        if variant in ['split_bank2', 'split_rom2']:
            cfg += 'clock_uncertainty=0ns\n'
        (dest / 'hls_config.cfg').write_text(cfg)
        shutil.copy2(Path(__file__).with_name('check.cpp'), dest / 'check.cpp')
        (dest / 'manifest.json').write_text(json.dumps(dict(variant=requested_variant, horizon=args.horizon, iterations=10,
            source_sha256=hashlib.sha256(code.encode()).hexdigest(), baseline_sha256=hashlib.sha256(original.encode()).hexdigest()), indent=2))
        print(dest, flush=True)


if __name__ == '__main__':
    main()
