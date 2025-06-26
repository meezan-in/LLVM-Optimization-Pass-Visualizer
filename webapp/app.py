from flask import Flask, request, render_template
import subprocess
import os
from ir_diff_tool import run_clang, run_opt, compare_ir, summarize_changes
import re
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch
from werkzeug.utils import secure_filename
import sys

app = Flask(__name__)

# Initialize the model and tokenizer
try:
    tokenizer = AutoTokenizer.from_pretrained("Salesforce/codet5-base")
    model = AutoModelForSeq2SeqLM.from_pretrained("Salesforce/codet5-base")
except Exception as e:
    print(f"Error loading model: {e}")
    tokenizer = None
    model = None

# Configure upload settings
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'cpp', 'cc', 'cxx'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def run_clang_with_debug(source_file, output_file="before.ll"):
    try:
        # First, try to compile with verbose output
        result = subprocess.run(
            ["clang", "-S", "-emit-llvm", "-O0", "-Xclang", "-disable-O0-optnone", source_file, "-o", output_file],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            # If compilation fails, try with C++ standard specified
            result = subprocess.run(
                ["clang++", "-std=c++17", "-S", "-emit-llvm", source_file, "-o", output_file],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                error_msg = f"Clang compilation failed:\n{result.stderr}"
                print(error_msg, file=sys.stderr)
                raise Exception(error_msg)
                
        return True
    except Exception as e:
        print(f"Error in run_clang_with_debug: {str(e)}", file=sys.stderr)
        raise

def generate_ai_summary(diff_output, opt_pass):
    if model is None or tokenizer is None:
        return "Model not available. Using basic summary."
    
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
        return "Error generating AI summary. Using basic summary."

def analyze_optimization_changes(diff_output, opt_pass):
    try:
        changes = []
        impact_levels = {
            'high': ['alloca', 'store', 'load', 'call'],
            'medium': ['br', 'ret', 'switch'],
            'low': ['attributes', 'metadata']
        }
        
        lines = diff_output.split('\n')
        
        for line in lines:
            if line.startswith('+') and not line.startswith('+++'):
                change = line[1:].strip()
                if change:
                    impact = 'low'
                    for level, keywords in impact_levels.items():
                        if any(keyword in change.lower() for keyword in keywords):
                            impact = level
                            break
                    
                    if 'alloca' in change:
                        desc = "Memory allocation operation"
                    elif 'store' in change:
                        desc = "Memory store operation"
                    elif 'load' in change:
                        desc = "Memory load operation"
                    elif 'call' in change:
                        desc = "Function call"
                    elif 'br' in change:
                        desc = "Branch instruction"
                    elif 'ret' in change:
                        desc = "Return instruction"
                    else:
                        desc = "Code modification"
                    
                    changes.append({
                        'description': desc,
                        'impact': impact,
                        'details': change
                    })
        
        ai_summary = generate_ai_summary(diff_output, opt_pass)
        
        if ai_summary == "Model not available. Using basic summary." or ai_summary.startswith("Error"):
            summary = f"The {opt_pass} optimization pass has been applied to your code. "
            
            if not changes:
                summary += "No significant changes were detected in the code."
            else:
                high_impact = sum(1 for c in changes if c['impact'] == 'high')
                medium_impact = sum(1 for c in changes if c['impact'] == 'medium')
                
                if high_impact > 0:
                    summary += f"Found {high_impact} high-impact changes that significantly affect memory operations and function calls. "
                if medium_impact > 0:
                    summary += f"Detected {medium_impact} medium-impact changes in control flow. "
                
                summary += "These optimizations aim to improve performance by reducing memory operations and simplifying control flow."
        else:
            summary = ai_summary
        
        return {
            'summary': summary,
            'key_changes': changes
        }
    except Exception as e:
        print(f"Error in analysis: {e}")
        return {
            'summary': f"Error analyzing changes: {str(e)}",
            'key_changes': []
        }

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    ai_analysis = None
    
    if request.method == "POST":
        opt_pass = request.form["opt_pass"]
        source_code = None
        
        if 'cppFile' in request.files:
            file = request.files['cppFile']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                with open(filepath, 'r') as f:
                    source_code = f.read()
                os.remove(filepath)
        
        if not source_code:
            source_code = request.form["source"]
        
        try:
            # Write the source code to a temporary file
            with open("example.cpp", "w") as f:
                f.write(source_code)

            # Use the new debug version of run_clang
            run_clang_with_debug("example.cpp")
            run_opt(opt_pass)
            diff_output = compare_ir(return_text=True)
            summary = summarize_changes(opt_pass, return_text=True)
            result = diff_output + "\n" + summary
            
            ai_analysis = analyze_optimization_changes(diff_output, opt_pass)
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error processing request: {error_msg}", file=sys.stderr)
            result = f"Error: {error_msg}"
            ai_analysis = {
                'summary': f"Error during analysis: {error_msg}",
                'key_changes': []
            }
    
    return render_template("index.html", 
                         result=result, 
                         ai_summary=ai_analysis['summary'] if ai_analysis else None, 
                         key_changes=ai_analysis['key_changes'] if ai_analysis else [])

if __name__ == "__main__":
    app.run(debug=True)
