from flask import Flask, render_template, request, jsonify, send_file
import os
import uuid
import json
import fitz  # PyMuPDF
import tempfile
from pathlib import Path

app = Flask(__name__, template_folder='templates')

# Configure upload folders
UPLOAD_FOLDER = Path(tempfile.gettempdir()) / 'pdf_converter_uploads'
PROCESSED_FOLDER = Path(tempfile.gettempdir()) / 'pdf_converter_processed'
UPLOAD_FOLDER.mkdir(exist_ok=True)
PROCESSED_FOLDER.mkdir(exist_ok=True)

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['PROCESSED_FOLDER'] = str(PROCESSED_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and file.filename.lower().endswith('.pdf'):
        # Generate unique filename
        filename = f"{uuid.uuid4()}.pdf"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Extract PDF info and first page preview
        try:
            pdf_info = extract_pdf_info(filepath)
            return jsonify({
                'success': True,
                'filename': filename,
                'pageCount': pdf_info['pageCount'],
                'previews': pdf_info['previews']
            })
        except Exception as e:
            return jsonify({'error': f'Error processing PDF: {str(e)}'}), 500
    
    return jsonify({'error': 'Invalid file format. Please upload a PDF.'}), 400

@app.route('/preview/<filename>/<int:page>')
def get_preview(filename, page):
    """Get preview image for a specific page"""
    preview_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}_p{page}.png")
    if os.path.exists(preview_path):
        return send_file(preview_path, mimetype='image/png')
    return jsonify({'error': 'Preview not found'}), 404

@app.route('/process', methods=['POST'])
def process_pdf():
    data = request.json
    filename = data.get('filename')
    dimensions = data.get('dimensions', [])
    exclusion_zones = data.get('exclusionZones', [])
    
    if not filename or not dimensions:
        return jsonify({'error': 'Missing required parameters'}), 400
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'PDF file not found'}), 404
    
    try:
        # Process PDF with user-selected dimensions
        output_path = process_dimensions(filepath, dimensions, exclusion_zones)
        
        # Return download path
        output_filename = os.path.basename(output_path)
        return jsonify({
            'success': True,
            'message': f'Successfully processed {len(dimensions)} dimensions',
            'processedFile': f'/download/{output_filename}'
        })
    except Exception as e:
        return jsonify({'error': f'Error processing PDF: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['PROCESSED_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

def extract_pdf_info(pdf_path):
    """Extract basic info and page previews from PDF"""
    doc = fitz.open(pdf_path)
    filename = os.path.basename(pdf_path)
    previews = []
    
    # Generate preview for each page
    for page_num in range(min(doc.page_count, 10)):  # Limit to first 10 pages
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))  # Scale factor for better quality
        preview_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}_p{page_num}.png")
        pix.save(preview_path)
        previews.append(f'/preview/{filename}/{page_num}')
    
    return {
        'pageCount': doc.page_count,
        'previews': previews
    }

def mm_to_inches(mm_value):
    """Convert millimeter value to inches with 3 decimal precision"""
    return round(float(mm_value) / 25.4, 3)

def process_dimensions(pdf_path, dimensions, exclusion_zones):
    """Process PDF with user-selected dimensions and exclusion zones"""
    doc = fitz.open(pdf_path)
    filename = f"converted_{uuid.uuid4()}.pdf"
    output_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
    
    # Process each dimension
    for dim in dimensions:
        if dim.get('exclude', False):
            continue  # Skip dimensions marked for exclusion
        
        # Check if inside any exclusion zone
        inside_exclusion = False
        for zone in exclusion_zones:
            if (zone.get('page') == dim.get('page') and
                zone.get('x') <= dim.get('x') <= zone.get('x') + zone.get('width') and
                zone.get('y') <= dim.get('y') <= zone.get('y') + zone.get('height')):
                inside_exclusion = True
                break
        
        if inside_exclusion:
            continue  # Skip dimensions in exclusion zones
        
        # Get page and convert value
        page_num = dim.get('page', 0)
        if 0 <= page_num < doc.page_count:
            page = doc[page_num]
            
            try:
                # Convert metric value to imperial
                metric_value = float(dim.get('value', 0))
                imperial_value = mm_to_inches(metric_value)
                
                # Add annotation to PDF
                rect = fitz.Rect(dim.get('x'), dim.get('y') + 15,  # Position annotation below original
                                dim.get('x') + 100, dim.get('y') + 30)
                
                # Create annotation
                page.insert_text(
                    point=fitz.Point(dim.get('x'), dim.get('y') + 15),
                    text=f"{imperial_value} in",
                    fontsize=10,
                    color=(1, 0, 0)  # Red text
                )
            except (ValueError, TypeError) as e:
                print(f"Error processing dimension: {e}")
                continue
    
    # Save the modified PDF
    doc.save(output_path)
    doc.close()
    
    return output_path

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)