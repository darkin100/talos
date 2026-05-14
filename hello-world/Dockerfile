# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/todo-api .

# Runtime stage
FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=builder /out/todo-api /todo-api
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/todo-api"]
