variable "project_id" {
  description = "GCP project that hosts the pipeline."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Scheduler, Artifact Registry and BigQuery."
  type        = string
  default     = "europe-west3"
}

variable "image" {
  description = "Full image URL (see README step 2). Leave empty on the first apply that creates the registry."
  type        = string
  default     = ""
}

variable "schedule" {
  description = "Cron schedule for the job."
  type        = string
  default     = "0 7 * * 1" # Mondays 07:00
}

variable "time_zone" {
  type    = string
  default = "Europe/Berlin"
}

variable "feeds" {
  description = "Comma-separated RSS/Atom feed URLs."
  type        = string
  default     = "https://cloud.google.com/feeds/gcp-release-notes.xml,https://cloudblog.withgoogle.com/rss/"
}

variable "youtube_queries" {
  description = "Comma-separated YouTube search queries."
  type        = string
  default     = "Google Cloud Vertex AI agents,Terraform Google Cloud"
}

variable "gemini_model" {
  type    = string
  default = "gemini-flash-latest"
}

variable "alert_email" {
  description = "Email for failure alerts. Empty disables the notification channel."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Protect the Cloud Run job and BigQuery tables from terraform destroy."
  type        = bool
  default     = false
}
