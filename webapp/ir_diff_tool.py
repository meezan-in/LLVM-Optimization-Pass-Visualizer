import subprocess
import sys
import argparse
import difflib
import os

def run_clang(source_file, output_file="before.ll"):
    print("🔧 Generating LLVM IR from C++...")
    subprocess.run(["clang", "-S", "-emit-llvm", source_file, "-o", output_file], check=True)

def run_opt(opt_pass, input_file="before.ll", output_file="after.ll"):
    print(f"🚀 Applying LLVM pass: {opt_pass} ...")
    subprocess.run(["opt", "-S", f"-passes={opt_pass}", input_file, "-o", output_file], check=True)

def compare_ir(before_file="before.ll", after_file="after.ll"):
    print("🔍 Comparing before and after IR...\n")
    with open(before_file) as f1, open(after_file) as f2:
        before_lines = f1.readlines()
        after_lines = f2.readlines()

    diff = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile="before.ll", tofile="after.ll",
        lineterm=""
    ))

    if not diff:
        print("✅ No semantic changes detected.")
    else:
        print("📄 IR Diff:")
        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                print(f"🟩 {line.strip()}")
            elif line.startswith('-') and not line.startswith('---'):
                print(f"🟥 {line.strip()}")

def summarize_changes(opt_pass):
    summaries = {
        "mem2reg": "🧠 mem2reg: Promoted stack memory (alloca) to SSA registers.",
        "loop-unroll": "🔁 loop-unroll: Duplicated loop body to reduce branching.",
        "simplifycfg": "📉 simplifycfg: Removed redundant branches / simplified control flow.",
        "instcombine": "⚙️ instcombine: Combined instructions into simpler forms.",
        "gvn": "🔄 gvn: Eliminated redundant expressions using global value numbering.",
        "dce": "🧹 dce: Removed dead code and unreachable instructions.",
    }
    print("\n📝 Summary:")
    print(summaries.get(opt_pass, f"{opt_pass}: Optimization applied."))

def main():
    parser = argparse.ArgumentParser(description="🔎 LLVM IR Optimization Visualizer CLI Tool")
    parser.add_argument("source", help="C++ source file (e.g. example.cpp)")
    parser.add_argument("--opt_pass", required=True, help="LLVM optimization pass (e.g. mem2reg, loop-unroll, simplifycfg)")

    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"❌ File not found: {args.source}")
        sys.exit(1)

    try:
        run_clang(args.source)
        run_opt(args.opt_pass)
        compare_ir()
        summarize_changes(args.opt_pass)
    except subprocess.CalledProcessError as e:
        print("❌ An error occurred while running LLVM tools.")
        sys.exit(1)

if __name__ == "__main__":
    main()
import difflib

def compare_ir(before_file="before.ll", after_file="after.ll", return_text=False):
    with open(before_file) as f1, open(after_file) as f2:
        before_lines = f1.readlines()
        after_lines = f2.readlines()

    diff = list(difflib.unified_diff(before_lines, after_lines, fromfile="before.ll", tofile="after.ll", lineterm=""))
    
    if return_text:
        if not diff:
            return "✅ No semantic changes detected."
        return "\n".join(diff)
    else:
        for line in diff:
            print(line)

def summarize_changes(opt_pass, return_text=False):
    summaries = {
        "mem2reg": "🧠 mem2reg: Promoted stack memory (alloca) to SSA registers.",
        "loop-unroll": "🔁 loop-unroll: Duplicated loop body for faster execution.",
        "simplifycfg": "🧹 simplifycfg: Removed redundant branches / simplified control flow.",
    }
    output = summaries.get(opt_pass, f"ℹ️ {opt_pass}: Optimization applied.")
    
    if return_text:
        return output
    else:
        # print("\n📝 Summary:")
        print(output)
