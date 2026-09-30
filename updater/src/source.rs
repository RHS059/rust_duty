use crate::{invalid, manifest::Asset, Error, Result, MAX_MANIFEST, REPOSITORY};
use reqwest::{
    blocking::{Client, Response},
    redirect::Policy,
    Url,
};
use semver::Version;
use std::{io::Read, time::Duration};

#[derive(Clone)]
pub struct Source {
    client: Client,
    #[cfg(test)]
    local: Option<String>,
}
fn github_path(url: &Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some("github.com")
        && url.path().starts_with(&format!("/{REPOSITORY}/releases/"))
        && url.username().is_empty()
        && url.password().is_none()
        && url.port().is_none()
}
fn safe_redirect(url: &Url) -> bool {
    github_path(url)
        || (url.scheme() == "https"
            && url.username().is_empty()
            && url.password().is_none()
            && url.port().is_none()
            && matches!(
                url.host_str(),
                Some("release-assets.githubusercontent.com" | "objects.githubusercontent.com")
            ))
}
impl Source {
    pub fn github() -> Result<Self> {
        let client = Client::builder()
            .user_agent("RustDutyLauncher/0.1 (RHS059/rust_duty)")
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(30))
            .redirect(Policy::custom(|attempt| {
                if attempt.previous().len() > 5
                    || !attempt.previous().first().is_some_and(github_path)
                    || !safe_redirect(attempt.url())
                {
                    attempt.error("redirect outside trusted GitHub release origin/CDN")
                } else {
                    attempt.follow()
                }
            }))
            .build()
            .map_err(|e| Error::Network(e.to_string()))?;
        Ok(Self {
            client,
            #[cfg(test)]
            local: None,
        })
    }
    #[cfg(test)]
    pub(crate) fn loopback(port: u16) -> Result<Self> {
        // Normal fixtures need the production-sized budget: response deadlines include
        // the caller's durable checkpoint writes, which are slower on Windows CI.
        Self::loopback_with_timeout(port, Duration::from_secs(30))
    }
    #[cfg(test)]
    pub(crate) fn loopback_with_timeout(port: u16, timeout: Duration) -> Result<Self> {
        Ok(Self {
            client: Client::builder()
                .timeout(timeout)
                .redirect(Policy::none())
                .build()
                .unwrap(),
            local: Some(format!("http://127.0.0.1:{port}")),
        })
    }
    fn root(&self) -> String {
        #[cfg(test)]
        if let Some(local) = &self.local {
            return local.clone();
        }
        format!("https://github.com/{REPOSITORY}/releases")
    }
    pub fn latest(&self, target: &str) -> Result<Vec<u8>> {
        if !crate::manifest::safe_name(target) {
            return Err(invalid("invalid target"));
        }
        let response = self
            .client
            .get(format!(
                "{}/latest/download/update-{target}.json",
                self.root()
            ))
            .send()
            .map_err(|e| Error::Network(e.to_string()))?;
        if !response.status().is_success() {
            return Err(Error::Network(format!(
                "manifest HTTP {} (a signed release channel may not exist yet)",
                response.status()
            )));
        }
        let mut bytes = Vec::new();
        response
            .take(MAX_MANIFEST + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| Error::Network(e.to_string()))?;
        if bytes.len() as u64 > MAX_MANIFEST {
            return Err(invalid("oversized manifest"));
        }
        Ok(bytes)
    }
    pub fn asset(
        &self,
        version: &Version,
        asset: &Asset,
        offset: u64,
        end: u64,
        etag: Option<&str>,
    ) -> Result<Response> {
        asset.validate()?;
        let mut request = self
            .client
            .get(format!(
                "{}/download/v{version}/{}",
                self.root(),
                asset.name
            ))
            .header("Accept-Encoding", "identity")
            .header("Range", format!("bytes={offset}-{end}"));
        if offset > 0 {
            if let Some(tag) = etag {
                request = request.header("If-Range", tag);
            }
        }
        request.send().map_err(|e| Error::Network(e.to_string()))
    }
}
#[cfg(test)]
pub(crate) fn redirect_allowed(url: &str) -> bool {
    Url::parse(url).is_ok_and(|u| safe_redirect(&u))
}
