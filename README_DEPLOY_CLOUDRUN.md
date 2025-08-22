# Google Cloud Build & Run Instructions for FastAPI Graduation Event App

## 1. Build & Deploy with Google Cloud Build and Cloud Run

### Build the Docker Image
```
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/grados-app
```

### Deploy to Cloud Run
```
gcloud run deploy grados-app \
  --image gcr.io/YOUR_PROJECT_ID/grados-app \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars REMOTE_MYSQL_USER=consulta_uam,REMOTE_MYSQL_PASSWORD=YOUR_PASSWORD,REMOTE_MYSQL_DB=cestudio_uam,REMOTE_MYSQL_CHARSET=utf8mb4,SENDER_EMAIL=no-reply@uam.edu.ve,SENDER_PASSWORD=YOUR_PASSWORD,SMTP_HOST=smtp.gmail.com,SMTP_PORT=587,LOCAL_PG_HOST=YOUR_PG_HOST,LOCAL_PG_PORT=5432,LOCAL_PG_USER=postgres,LOCAL_PG_PASSWORD=YOUR_PG_PASSWORD,LOCAL_PG_DB=local_event_control_db
```
- Replace `YOUR_PROJECT_ID`, `YOUR_PASSWORD`, `YOUR_PG_HOST`, and `YOUR_PG_PASSWORD` with your actual values.
- You can also use `--env-vars-file` and a YAML file for secrets.

## 2. Notes
- The Dockerfile is set up to use `uvicorn main:app --host 0.0.0.0 --port 8080`.
- Make sure your main FastAPI app is in `main.py` and the app variable is named `app`.
- Environment variables are set in Cloud Run, not in the Docker image.
- If you want to serve static files or icons, add them to a `static/` directory and mount it in FastAPI.

## 3. Useful Links
- [Cloud Run Quickstart](https://cloud.google.com/run/docs/quickstarts/build-and-deploy)
- [Cloud Build Documentation](https://cloud.google.com/build/docs/)
- [FastAPI Deployment Docs](https://fastapi.tiangolo.com/deployment/)

---

## Troubleshooting
- If you see errors about missing environment variables, double-check your `--set-env-vars` or env file.
- If you see `TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'`, make sure you are using Uvicorn (not Gunicorn alone).
- To update your app, just redeploy with the same service name.
