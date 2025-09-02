import streamlit as st
import requests
import time

def poll_job_status(job_id: str):
    """
    Polls the backend for the status of a background job and displays it in the UI.

    Args:
        job_id: The ID of the job to poll.
    """
    status_placeholder = st.empty()

    while True:
        try:
            status_url = f"{st.session_state.API_BASE_URL}/jobs/{job_id}"
            response = requests.get(status_url)
            response.raise_for_status()

            job_data = response.json()
            status = job_data.get("status")
            details = job_data.get("details")

            if status == "completed":
                status_placeholder.success(f"✅ **Job Complete:** {details}")
                # Check for generated files and store them in the session state
                if "generated_files" in job_data:
                    st.session_state.generated_metadata_files = job_data["generated_files"]
                break
            elif status == "failed":
                status_placeholder.error(f"❌ **Job Failed:** {details}")
                break
            else:
                status_placeholder.info(f"⏳ **In Progress:** {details}")

        except requests.exceptions.RequestException as e:
            status_placeholder.error(f"Could not get job status. Connection error: {e}")
            break
        
        time.sleep(5) # Poll every 5 seconds

def poll_multiple_job_statuses(jobs: list):
    """
    Polls the backend for the status of multiple background jobs and displays them in the UI.

    Args:
        jobs: A list of job dictionaries, where each dictionary has at least a "job_id" and "status".
    """
    if not jobs:
        return

    st.markdown("---")
    st.subheader("Job Status")

    # Create a copy of the list to iterate over, so we can modify the original
    jobs_to_poll = list(jobs)

    for job in jobs_to_poll:
        if job['status'] in ["pending", "in_progress"]:
            try:
                status_url = f"{st.session_state.API_BASE_URL}/jobs/{job['job_id']}"
                response = requests.get(status_url)
                response.raise_for_status()
                
                job_data = response.json()
                job['status'] = job_data.get("status")
                details = job_data.get("details", "No details.")
                
                if job['status'] == "completed":
                    st.success(f"✅ **{job.get('clip', job['job_id'])}**: {details}")
                elif job['status'] == "failed":
                    st.error(f"❌ **{job.get('clip', job['job_id'])}**: {details}")
                else: # in_progress
                    st.info(f"⏳ **{job.get('clip', job['job_id'])}**: {details}")

            except requests.exceptions.RequestException as e:
                st.error(f"Could not get status for job {job['job_id']}. Error: {e}")
                job['status'] = "error" # Stop polling for this job

    # Filter out completed/failed jobs from the session state list
    st.session_state.refine_jobs = [j for j in jobs if j['status'] in ["pending", "in_progress"]]

    # If there are still jobs running, schedule a rerun
    if st.session_state.refine_jobs:
        time.sleep(5)
        st.rerun()
    else:
        st.info("All jobs have finished.")
def get_gcs_files(bucket_name, prefix):
    """Fetches a list of files from a GCS bucket folder."""
    api_url = st.session_state.API_BASE_URL
    try:
        response = requests.get(
            f"{api_url}/gcs/list",
            params={"gcs_bucket": bucket_name, "prefix": prefix},
        )
        response.raise_for_status()
        return response.json().get("files", [])
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch files from GCS: {e}")
        return []