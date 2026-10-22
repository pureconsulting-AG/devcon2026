# Kranich REST API (for partners)

Base URL: `https://api.nordlicht.example/kranich/v2`

## Authentication
Send your API key in the header `X-Kranich-Key`. Keys expire after **365 days**;
request a new one from sales before expiry.

## Endpoints

### GET /shipments/{id}
Returns the current status and the last 20 scans of a shipment.

### POST /shipments/{id}/redirect
Redirects a shipment to a pickup point. Only possible **before the first delivery attempt**.
Body: `{"pickup_point": "<id>"}`

## Rate limits
120 requests per minute per key. Exceeding the limit returns HTTP 429 with a
`Retry-After` header (seconds).
