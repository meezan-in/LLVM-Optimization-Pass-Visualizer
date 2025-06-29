import subprocess
import sys
import argparse
import difflib
import os
import re
from typing import List, Dict, Tuple, Optional
import json

# Optional: Import transformers for GenAI summary
try:
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import torch
    tokenizer = AutoTokenizer.from_pretrained("Salesforce/codet5-base")
    model = AutoModelForSeq2SeqLM.from_pretrained("Salesforce/codet5-base")
except Exception:
    tokenizer = None
    model = None

class IRDiffTool:
    def __init__(self):
        self.instruction_patterns = {
            'alloca': r'%[\w.]+ = alloca',
            'store': r'store .*',
            'load': r'%[\w.]+ = load',
            'call': r'%[\w.]+ = call',
            'br': r'br .*',
            'ret': r'ret .*',
            'switch': r'switch .*',
            'loop': r'!llvm\.loop',
        }

    def run_clang(self, source_file: str, output_file: str = "before.ll", opt_level: str = "O0") -> bool:
        """Generate LLVM IR from C++ source with specified optimization level."""
        try:
            cmd = ["clang++", f"-{opt_level}", "-S", "-emit-llvm", source_file, "-o", output_file]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error generating IR: {e.stderr}", file=sys.stderr)
            return False

    def run_opt(self, opt_pass: str, input_file: str = "before.ll", output_file: str = "after.ll") -> bool:
        """Apply LLVM optimization pass."""
        try:
            cmd = ["opt", "-S", f"-passes={opt_pass}", input_file, "-o", output_file]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error applying optimization: {e.stderr}", file=sys.stderr)
            return False

    def run_llvm_diff(self, before_file: str, after_file: str) -> Optional[str]:
        try:
            result = subprocess.run(["llvm-diff", before_file, after_file], capture_output=True, text=True)
            if result.returncode == 0 or result.returncode == 1:  # 1 means diff found
                return result.stdout
            else:
                return None
        except Exception as e:
            print(f"Error running llvm-diff: {e}", file=sys.stderr)
            return None

    def annotate_diff(self, diff_text: str) -> str:
        # Add simple annotations for common IR changes
        lines = diff_text.split('\n')
        annotated = []
        for line in lines:
            explanation = ""
            if 'alloca' in line:
                explanation = "// Stack allocation (alloca) changed"
            elif 'store' in line:
                explanation = "// Store instruction changed"
            elif 'load' in line:
                explanation = "// Load instruction changed"
            elif 'call' in line:
                explanation = "// Function call changed"
            elif 'br' in line:
                explanation = "// Branch instruction changed"
            elif 'ret' in line:
                explanation = "// Return instruction changed"
            elif 'loop' in line:
                explanation = "// Loop metadata changed"
            if explanation:
                annotated.append(f"{line} {explanation}")
            else:
                annotated.append(line)
        return '\n'.join(annotated)

    def parse_ir(self, ir_file: str) -> Dict:
        """Parse LLVM IR into a structured format."""
        with open(ir_file) as f:
            content = f.read()

        # Split into functions
        functions = {}
        current_func = None
        current_blocks = []
        current_block = []

        for line in content.split('\n'):
            if line.startswith('define'):
                if current_func:
                    functions[current_func] = current_blocks
                current_func = line.split('@')[1].split('(')[0]
                current_blocks = []
                current_block = [line]
            elif line.startswith('  '):
                if line.strip().startswith(';'):
                    continue
                if line.strip().startswith('%') and not line.strip().startswith('%0'):
                    if current_block:
                        current_blocks.append(current_block)
                    current_block = [line]
                else:
                    current_block.append(line)
            else:
                if current_block:
                    current_blocks.append(current_block)
                    current_block = []

        if current_func:
            functions[current_func] = current_blocks

        return functions

    def structural_diff(self, before_ir: Dict, after_ir: Dict) -> Dict:
        """Perform structural diff of IR, focusing on meaningful transformations."""
        changes = {
            'added_functions': [],
            'removed_functions': [],
            'modified_functions': {},
            'instruction_changes': {
                'added': [],
                'removed': [],
                'modified': []
            }
        }

        # Compare functions
        for func in set(before_ir.keys()) | set(after_ir.keys()):
            if func not in before_ir:
                changes['added_functions'].append(func)
            elif func not in after_ir:
                changes['removed_functions'].append(func)
            else:
                func_changes = self._compare_function(before_ir[func], after_ir[func])
                if func_changes:
                    changes['modified_functions'][func] = func_changes

        return changes

    def _compare_function(self, before_blocks: List[List[str]], after_blocks: List[List[str]]) -> Dict:
        """Compare function blocks and instructions."""
        changes = {
            'added_blocks': [],
            'removed_blocks': [],
            'modified_blocks': {}
        }

        # Compare blocks
        for i, (before_block, after_block) in enumerate(zip(before_blocks, after_blocks)):
            if before_block != after_block:
                block_changes = self._compare_instructions(before_block, after_block)
                if block_changes:
                    changes['modified_blocks'][i] = block_changes

        return changes

    def _compare_instructions(self, before_insts: List[str], after_insts: List[str]) -> Dict:
        """Compare instructions within a block."""
        changes = {
            'added': [],
            'removed': [],
            'modified': []
        }

        # Compare instructions
        for before_inst, after_inst in zip(before_insts, after_insts):
            if before_inst != after_inst:
                changes['modified'].append({
                    'before': before_inst,
                    'after': after_inst
                })

        return changes

    def generate_side_by_side_diff(self, before_file: str, after_file: str) -> str:
        """Generate side-by-side diff view of IR files."""
        with open(before_file) as f1, open(after_file) as f2:
            before_lines = f1.readlines()
            after_lines = f2.readlines()

        # Use difflib for initial diff
        diff = list(difflib.unified_diff(
            before_lines, after_lines,
            fromfile="Before", tofile="After",
            lineterm=""
        ))

        # Format for side-by-side view
        output = []
        current_section = []
        
        for line in diff:
            if line.startswith('@@'):
                if current_section:
                    output.extend(self._format_side_by_side(current_section))
                current_section = []
            else:
                current_section.append(line)

        if current_section:
            output.extend(self._format_side_by_side(current_section))

        return '\n'.join(output)

    def _format_side_by_side(self, section: List[str]) -> List[str]:
        """Format a section of diff for side-by-side view."""
        output = []
        before_lines = []
        after_lines = []
        
        for line in section:
            if line.startswith('-'):
                before_lines.append(line[1:])
            elif line.startswith('+'):
                after_lines.append(line[1:])
            else:
                if before_lines or after_lines:
                    output.extend(self._align_lines(before_lines, after_lines))
                    before_lines = []
                    after_lines = []
                output.append(line)

        if before_lines or after_lines:
            output.extend(self._align_lines(before_lines, after_lines))

        return output

    def _align_lines(self, before: List[str], after: List[str]) -> List[str]:
        """Align before and after lines for side-by-side view."""
        output = []
        max_before = max(len(line) for line in before) if before else 0
        max_after = max(len(line) for line in after) if after else 0

        for b, a in zip(before, after):
            output.append(f"{b.rstrip():<{max_before}} | {a.rstrip()}")
        
        # Handle remaining lines
        if len(before) > len(after):
            for b in before[len(after):]:
                output.append(f"{b.rstrip():<{max_before}} |")
        elif len(after) > len(before):
            for a in after[len(before):]:
                output.append(f"{'':<{max_before}} | {a.rstrip()}")

        return output

    def analyze_changes(self, changes: Dict) -> Dict:
        """Analyze the structural changes and categorize them."""
        analysis = {
            'optimization_effects': [],
            'performance_impact': 'low',
            'key_transformations': []
        }

        # Analyze function changes
        if changes['added_functions']:
            analysis['key_transformations'].append({
                'type': 'function_addition',
                'count': len(changes['added_functions']),
                'description': f"Added {len(changes['added_functions'])} new functions"
            })

        if changes['removed_functions']:
            analysis['key_transformations'].append({
                'type': 'function_removal',
                'count': len(changes['removed_functions']),
                'description': f"Removed {len(changes['removed_functions'])} functions"
            })

        # Analyze instruction changes
        for inst_type, insts in changes['instruction_changes'].items():
            if insts:
                analysis['key_transformations'].append({
                    'type': f'instruction_{inst_type}',
                    'count': len(insts),
                    'description': f"{len(insts)} instructions {inst_type}"
                })

        # Determine performance impact
        if any(t['type'] in ['instruction_removal', 'function_removal'] for t in analysis['key_transformations']):
            analysis['performance_impact'] = 'high'
        elif any(t['type'] in ['instruction_modified', 'function_modified'] for t in analysis['key_transformations']):
            analysis['performance_impact'] = 'medium'

        return analysis

    def generate_ai_summary(self, diff_output: str, opt_pass: str) -> str:
        if model is None or tokenizer is None:
            return "[GenAI model not available. Basic summary only.]"
        try:
            input_text = f"Optimization pass: {opt_pass}\nChanges:\n{diff_output}"
            inputs = tokenizer.encode(input_text, return_tensors="pt", max_length=512, truncation=True)
            outputs = model.generate(
                inputs,
                max_length=150,
                num_beams=4,
                temperature=0.7,
                top_p=0.95,
                do_sample=True
            )
            summary = tokenizer.decode(outputs[0], skip_special_tokens=True)
            return summary
        except Exception as e:
            print(f"Error generating AI summary: {e}")
            return "[Error generating AI summary.]"

def main():
    parser = argparse.ArgumentParser(description="🔎 LLVM IR Optimization Visualizer CLI Tool")
    parser.add_argument("source", help="C++ source file (e.g. example.cpp)")
    parser.add_argument("--opt_pass", required=True, help="LLVM optimization pass (e.g. mem2reg, loop-unroll, simplifycfg)")
    parser.add_argument("--opt_level", default="O0", choices=["O0", "O1", "O2", "O3"], help="Optimization level")
    parser.add_argument("--output", choices=["text", "json", "side-by-side", "annotated", "llvm-diff"], default="text", help="Output format")
    parser.add_argument("--genai", action="store_true", help="Show GenAI summary")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"❌ File not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    tool = IRDiffTool()
    
    try:
        # Generate IR
        if not tool.run_clang(args.source, "before.ll", args.opt_level):
            sys.exit(1)
        
        # Apply optimization
        if not tool.run_opt(args.opt_pass):
            sys.exit(1)

        # Output selection
        if args.output == "llvm-diff":
            diff = tool.run_llvm_diff("before.ll", "after.ll")
            if diff:
                print(diff)
            else:
                print("[llvm-diff failed or not available, falling back to Python diff]")
                args.output = "annotated"
        elif args.output == "side-by-side":
            print(tool.generate_side_by_side_diff("before.ll", "after.ll"))
        elif args.output == "annotated":
            with open("before.ll") as f1, open("after.ll") as f2:
                before = f1.readlines()
                after = f2.readlines()
            diff = list(difflib.unified_diff(before, after, fromfile="Before", tofile="After", lineterm=""))
            annotated = tool.annotate_diff('\n'.join(diff))
            print(annotated)
        elif args.output == "text":
            with open("before.ll") as f1, open("after.ll") as f2:
                before = f1.readlines()
                after = f2.readlines()
            diff = list(difflib.unified_diff(before, after, fromfile="Before", tofile="After", lineterm=""))
            print(''.join(diff))
        elif args.output == "json":
            # For now, just output the raw diff
            with open("before.ll") as f1, open("after.ll") as f2:
                before = f1.readlines()
                after = f2.readlines()
            diff = list(difflib.unified_diff(before, after, fromfile="Before", tofile="After", lineterm=""))
            print(json.dumps({'diff': diff}))
        # GenAI summary
        if args.genai:
            with open("before.ll") as f1, open("after.ll") as f2:
                before = f1.readlines()
                after = f2.readlines()
            diff = list(difflib.unified_diff(before, after, fromfile="Before", tofile="After", lineterm=""))
            summary = tool.generate_ai_summary('\n'.join(diff), args.opt_pass)
            print("\n=== GenAI Summary ===\n" + summary)
    except Exception as e:
        print(f"❌ Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
