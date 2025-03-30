document.addEventListener('DOMContentLoaded', function() {
    // Find all paste areas
    const pasteAreas = document.querySelectorAll('.paste-area');
    
    if (pasteAreas.length > 0) {
        pasteAreas.forEach(pasteArea => {
            pasteArea.addEventListener('paste', function(e) {
                const items = (e.clipboardData || e.originalEvent.clipboardData).items;
                
                for (let i = 0; i < items.length; i++) {
                    if (items[i].type.indexOf('image') !== -1) {
                        // Show loading indicator
                        pasteArea.innerHTML = '<div class="text-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div><p>Processing image...</p></div>';
                        
                        // Get the image blob
                        const blob = items[i].getAsFile();
                        
                        // Create a FileReader to read the image
                        const reader = new FileReader();
                        
                        reader.onload = function(event) {
                            // Check size of base64 data
                            const dataSize = event.target.result.length;
                            const maxSize = 10 * 1024 * 1024; // 10MB limit for base64 data
                            
                            if (dataSize > maxSize) {
                                // If image is too large, show error and option to resize
                                pasteArea.innerHTML = `
                                    <div class="alert alert-danger">
                                        <h5>Image too large (${Math.round(dataSize/1024/1024)}MB)</h5>
                                        <p>The pasted image is too large to upload directly. Please try one of these options:</p>
                                        <ol>
                                            <li>Resize the image before pasting</li>
                                            <li>Save the image to your device and use the file upload option</li>
                                            <li><button id="resize-image-btn" class="btn btn-sm btn-primary">Let me resize it for you</button></li>
                                        </ol>
                                    </div>
                                `;
                                
                                // Add resize functionality
                                document.getElementById('resize-image-btn').addEventListener('click', function() {
                                    resizeImage(blob, 1500, function(resizedBlob) {
                                        // Create a preview of the resized image
                                        const resizedReader = new FileReader();
                                        resizedReader.onload = function(e) {
                                            // Update the preview
                                            pasteArea.innerHTML = `
                                                <div class="text-center">
                                                    <img src="${e.target.result}" alt="Pasted image" style="max-width: 100%; max-height: 300px;" class="img-thumbnail">
                                                    <p>Image resized successfully</p>
                                                </div>
                                            `;
                                            
                                            // Update the hidden field
                                            document.getElementById('image_data').value = e.target.result;
                                        };
                                        resizedReader.readAsDataURL(resizedBlob);
                                    });
                                });
                                
                            } else {
                                // If image is within acceptable size, display preview
                                pasteArea.innerHTML = `
                                    <div class="text-center">
                                        <img src="${event.target.result}" alt="Pasted image" style="max-width: 100%; max-height: 300px;" class="img-thumbnail">
                                    </div>
                                `;
                                
                                // Update the hidden field with the base64 data
                                document.getElementById('image_data').value = event.target.result;
                            }
                        };
                        
                        // Read the image as Data URL (base64)
                        reader.readAsDataURL(blob);
                        break;
                    }
                }
            });
            
            // Add visual cue that this area accepts pastes
            pasteArea.classList.add('paste-ready');
        });
    }
    
    // Function to resize an image using canvas
    function resizeImage(blob, maxDimension, callback) {
        const img = new Image();
        img.onload = function() {
            // Calculate new dimensions
            let width = img.width;
            let height = img.height;
            
            if (width > height) {
                if (width > maxDimension) {
                    height = Math.round(height * (maxDimension / width));
                    width = maxDimension;
                }
            } else {
                if (height > maxDimension) {
                    width = Math.round(width * (maxDimension / height));
                    height = maxDimension;
                }
            }
            
            // Create a canvas to resize the image
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            
            // Draw the resized image
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, width, height);
            
            // Convert to blob
            canvas.toBlob(function(resizedBlob) {
                callback(resizedBlob);
            }, 'image/jpeg', 0.85); // Compress as JPEG with 85% quality
        };
        
        // Load the image from blob
        img.src = URL.createObjectURL(blob);
    }
});