output "image_repository" {
  description = "Push the image here: <repo>/digest:latest"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}"
}

output "bigquery_dataset" {
  value = google_bigquery_dataset.digest.dataset_id
}

output "run_now" {
  description = "Trigger one execution manually."
  value       = var.image == "" ? "set var.image first" : "gcloud run jobs execute digest --region ${var.region} --project ${var.project_id} --wait"
}
