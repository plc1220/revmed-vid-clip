const fileInput = document.getElementById('file-input');
const statusDiv = document.getElementById('status');
const startButton = document.getElementById('start-button');
const apiBaseUrl = document.body.getAttribute('data-api-base-url');
const gcsBucket = document.body.getAttribute('data-gcs-bucket');
const workspace = document.body.getAttribute('data-workspace');

// Function to communicate from the component to Streamlit
function setComponentValue(value) {
    try {
        console.log('Sending value to Streamlit:', value);
        // Try multiple methods to communicate with Streamlit
        
        // Method 1: Direct postMessage
        if (typeof window.parent !== 'undefined' && window.parent.postMessage) {
            window.parent.postMessage({
                type: 'streamlit:componentValue',
                value: value
            }, '*');
        }
        
        // Method 2: Try to use window.parent.streamlitSetComponentValue if available
        if (typeof window.parent.streamlitSetComponentValue === 'function') {
            window.parent.streamlitSetComponentValue(value);
        }
        
        // Method 3: Set a property that Streamlit might check
        if (window.parent && window.parent.document) {
            window.parent.document.streamlitComponentValue = value;
        }
        
    } catch (e) {
        console.error('Error sending value to Streamlit:', e);
    }
}

async function uploadFile(file) {
    if (!file) {
        statusDiv.innerText = 'Please select a file first.';
        return;
    }

    statusDiv.innerText = 'Requesting secure upload link...';
    startButton.disabled = true;

    try {
        // 1. Get a signed URL from the backend
        const signedUrlResponse = await fetch(`${apiBaseUrl}/generate-upload-url/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                file_name: file.name,
                content_type: file.type,
                gcs_bucket: gcsBucket,
                workspace: workspace
            })
        });

        if (!signedUrlResponse.ok) {
            const errorText = await signedUrlResponse.text();
            throw new Error(`Failed to get signed URL: ${signedUrlResponse.status} ${errorText}`);
        }

        const uploadData = await signedUrlResponse.json();
        const { upload_url, gcs_blob_name } = uploadData;

        statusDiv.innerText = `Uploading ${file.name} directly to storage...`;

        // 2. Upload the file directly to GCS using the signed URL
        const uploadResponse = await fetch(upload_url, {
            method: 'PUT',
            body: file,
            headers: { 'Content-Type': file.type }
        });

        if (!uploadResponse.ok) {
            const errorText = await uploadResponse.text();
            throw new Error(`Upload failed: ${uploadResponse.status} ${errorText}`);
        }

        statusDiv.innerHTML = `✅ Upload successful! <br>File: gs://${gcsBucket}/${gcs_blob_name}. Refresh the page to see your uploaded video`;
        
        // 3. Send the GCS blob name back to the Streamlit app
        setComponentValue(JSON.stringify({ "gcs_blob_name": gcs_blob_name, "file_name": file.name }));

    } catch (error) {
        statusDiv.innerText = `❌ Error: ${error.message}`;
        startButton.disabled = false;
    }
}

startButton.addEventListener('click', () => {
    const file = fileInput.files[0];
    uploadFile(file);
});

// Let parent know we're ready
try {
    if (typeof window.parent !== 'undefined' && window.parent.postMessage) {
        window.parent.postMessage({
            type: 'streamlit:componentReady',
            height: 150
        }, '*');
    }
} catch (e) {
    console.error('Error sending ready message:', e);
}