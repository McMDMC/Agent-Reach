locals {
  apis = [
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

# ---------- Registry ----------
resource "google_artifact_registry_repository" "repo" {
  repository_id = "digest"
  location      = var.region
  format        = "DOCKER"
  description   = "Images for the agent-reach digest job"

  cleanup_policies {
    id     = "keep-last-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }
  cleanup_policies {
    id     = "delete-rest"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------- BigQuery ----------
resource "google_bigquery_dataset" "digest" {
  dataset_id                 = "agent_reach_digest"
  location                   = var.region
  delete_contents_on_destroy = !var.deletion_protection

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "items" {
  dataset_id          = google_bigquery_dataset.digest.dataset_id
  table_id            = "items"
  deletion_protection = var.deletion_protection

  time_partitioning {
    type  = "DAY"
    field = "collected_at"
  }

  schema = jsonencode([
    { name = "id", type = "STRING", mode = "REQUIRED" },
    { name = "source", type = "STRING", mode = "REQUIRED" },
    { name = "kind", type = "STRING", mode = "REQUIRED" },
    { name = "title", type = "STRING", mode = "NULLABLE" },
    { name = "url", type = "STRING", mode = "REQUIRED" },
    { name = "summary", type = "STRING", mode = "NULLABLE" },
    { name = "published", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "collected_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "digests" {
  dataset_id          = google_bigquery_dataset.digest.dataset_id
  table_id            = "digests"
  deletion_protection = var.deletion_protection

  schema = jsonencode([
    { name = "run_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "item_count", type = "INTEGER", mode = "REQUIRED" },
    { name = "digest", type = "STRING", mode = "NULLABLE" },
  ])
}

# ---------- Identities (least privilege) ----------
resource "google_service_account" "job" {
  account_id   = "digest-job"
  display_name = "Digest Cloud Run job"
}

resource "google_service_account" "scheduler" {
  account_id   = "digest-scheduler"
  display_name = "Digest Cloud Scheduler"
}

# Write only to this dataset, run query jobs, call Gemini. Nothing else.
resource "google_bigquery_dataset_iam_member" "job_editor" {
  dataset_id = google_bigquery_dataset.digest.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.job.email}"
}

resource "google_project_iam_member" "job_bq_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.job.email}"
}

resource "google_project_iam_member" "job_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.job.email}"
}

# ---------- Cloud Run Job ----------
resource "google_cloud_run_v2_job" "digest" {
  count               = var.image == "" ? 0 : 1
  name                = "digest"
  location            = var.region
  deletion_protection = var.deletion_protection

  template {
    template {
      service_account = google_service_account.job.email
      timeout         = "600s"
      max_retries     = 1

      containers {
        image = var.image

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "BQ_DATASET"
          value = google_bigquery_dataset.digest.dataset_id
        }
        env {
          name  = "FEEDS"
          value = var.feeds
        }
        env {
          name  = "YT_QUERIES"
          value = var.youtube_queries
        }
        env {
          name  = "GEMINI_MODEL"
          value = var.gemini_model
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_bigquery_dataset_iam_member.job_editor,
    google_project_iam_member.job_bq_user,
    google_project_iam_member.job_vertex,
  ]
}

# ---------- Scheduler ----------
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  count    = var.image == "" ? 0 : 1
  name     = google_cloud_run_v2_job.digest[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "weekly" {
  count     = var.image == "" ? 0 : 1
  name      = "digest-weekly"
  region    = var.region
  schedule  = var.schedule
  time_zone = var.time_zone

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.digest[0].name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------- Alerting ----------
resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  display_name = "Digest job alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "job_errors" {
  display_name = "Digest job: ERROR log"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run job logged ERROR or higher"

    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_job"
        resource.labels.job_name="digest"
        severity>=ERROR
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "3600s"
    }
    auto_close = "86400s"
  }

  notification_channels = google_monitoring_notification_channel.email[*].id

  depends_on = [google_project_service.apis]
}
