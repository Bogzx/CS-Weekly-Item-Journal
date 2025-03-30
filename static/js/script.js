// JavaScript for clipboard paste functionality

document.addEventListener('DOMContentLoaded', function() {
    const pasteArea = document.getElementById('paste-area');
    const imageDataInput = document.getElementById('image-data');
    const fileInput = document.getElementById('file-input');
    const uploadForm = document.getElementById('upload-form');

    if (pasteArea && imageDataInput) {
        // Handle paste event
        document.addEventListener('paste', function(event) {
            // Check if we're focused on the paste area or the document
            if (document.activeElement === pasteArea || document.activeElement === document.body) {
                const items = (event.clipboardData || event.originalEvent.clipboardData).items;
                
                for (let i = 0; i < items.length; i++) {
                    if (items[i].type.indexOf('image') !== -1) {
                        const blob = items[i].getAsFile();
                        const reader = new FileReader();
                        
                        reader.onload = function(e) {
                            const imageData = e.target.result;
                            imageDataInput.value = imageData;
                            
                            // Clear any existing content
                            pasteArea.innerHTML = '';
                            pasteArea.classList.add('has-image');
                            
                            // Create and add the image preview
                            const img = document.createElement('img');
                            img.src = imageData;
                            img.className = 'paste-preview';
                            pasteArea.appendChild(img);
                            
                            // Add a clear button
                            const clearBtn = document.createElement('div');
                            clearBtn.className = 'paste-clear';
                            clearBtn.innerHTML = '&times;';
                            clearBtn.addEventListener('click', function(e) {
                                e.stopPropagation();
                                resetPasteArea();
                            });
                            pasteArea.appendChild(clearBtn);
                            
                            // Clear file input to avoid confusion
                            if (fileInput) {
                                fileInput.value = '';
                            }
                        };
                        
                        reader.readAsDataURL(blob);
                        break;
                    }
                }
            }
        });
        
        // Make paste area clickable
        pasteArea.addEventListener('click', function() {
            // If we have an image already, don't do anything (let the clear button handle it)
            if (pasteArea.classList.contains('has-image')) {
                return;
            }
            
            // Create a temporary textarea to capture the paste event
            const textarea = document.createElement('textarea');
            textarea.style.position = 'fixed';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.focus();
            
            setTimeout(function() {
                document.body.removeChild(textarea);
                pasteArea.focus();
            }, 100);
        });
        
        // Handle file input changes
        if (fileInput) {
            fileInput.addEventListener('change', function() {
                // If a file is selected, reset the paste area
                if (fileInput.files.length > 0) {
                    resetPasteArea();
                }
            });
        }
        
        // Reset the paste area
        function resetPasteArea() {
            pasteArea.innerHTML = 'Click here and press Ctrl+V to paste an image from clipboard';
            pasteArea.classList.remove('has-image');
            imageDataInput.value = '';
        }
        
        // Handle drag and drop events
        pasteArea.addEventListener('dragover', function(e) {
            e.preventDefault();
            pasteArea.classList.add('dragover');
        });
        
        pasteArea.addEventListener('dragleave', function() {
            pasteArea.classList.remove('dragover');
        });
        
        pasteArea.addEventListener('drop', function(e) {
            e.preventDefault();
            pasteArea.classList.remove('dragover');
            
            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];
                if (file.type.indexOf('image') !== -1) {
                    // Update file input if it exists
                    if (fileInput) {
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(file);
                        fileInput.files = dataTransfer.files;
                        
                        // Reset paste area
                        resetPasteArea();
                    }
                }
            }
        });
    }
    
    // Handle form submission
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            // If neither file nor image data is provided, prevent submission
            if ((!fileInput || fileInput.files.length === 0) && 
                (!imageDataInput || !imageDataInput.value)) {
                e.preventDefault();
                alert('Please select or paste an image first.');
            }
        });
    }
});