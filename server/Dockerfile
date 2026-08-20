FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS web-build

WORKDIR /web

COPY web/package*.json ./
RUN npm ci

COPY web ./
RUN npm run build

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 roomcam \
    && useradd --uid 10001 --gid roomcam --no-create-home --shell /usr/sbin/nologin roomcam

COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ADD --chown=roomcam:roomcam --chmod=0444 \
    --checksum=sha256:42fb3d70ffb7bb37dd518f730f7be784b831c2078f30c497d0019cc2e987fa26 \
    https://raw.githubusercontent.com/google-coral/test_data/master/ssd_mobilenet_v2_coco_quant_postprocess.tflite \
    /app/models/ssd_mobilenet_v2_int8.tflite
COPY --chown=roomcam:roomcam server/app ./app
COPY --chown=roomcam:roomcam --from=web-build /web/dist /app/web/dist

USER roomcam

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"]
