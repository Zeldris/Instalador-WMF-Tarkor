FROM registry.example.com:5000/team/base:2.1 AS build
RUN make
FROM python:3.12-slim@sha256:0123abcd AS runtime
COPY --from=build /out /app
FROM runtime
