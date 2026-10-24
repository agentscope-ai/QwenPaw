//! Versioned contract negotiation and routing over the shared IPC connection.
//!
//! Authentication and framing stay in `connection`; product vocabulary stays
//! in its contract dispatcher. P1 advertises only Computer Use. P2 can add
//! EventStream here without changing capability authentication or transport.

use std::io::{Read, Write};
use std::sync::Arc;

use serde_json::{json, Map, Value};

use super::dispatch::dispatch_request;
use super::event_stream::EventStreamConnection;
use super::service::DesktopAutomationService;
use super::state::ServerState;
use super::{
    COMPUTER_USE_CONTRACT, COMPUTER_USE_CONTRACT_VERSION, COMPUTER_USE_FEATURES,
    EVENT_STREAM_CONTRACT, EVENT_STREAM_CONTRACT_VERSION, EVENT_STREAM_FEATURE, PROTOCOL_VERSION,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Contract {
    ComputerUse,
    EventStream,
}

pub(super) enum ContractState {
    ComputerUse(ServerState),
    EventStream(EventStreamConnection),
}

impl Contract {
    /// Missing `contract` means Computer Use for released legacy v2 clients.
    pub(super) fn negotiate(
        params: &Map<String, Value>,
        service: &DesktopAutomationService,
    ) -> Result<Self, (&'static str, String)> {
        let requested = params
            .get("contract")
            .and_then(Value::as_str)
            .unwrap_or(COMPUTER_USE_CONTRACT);
        match requested {
            COMPUTER_USE_CONTRACT => Ok(Self::ComputerUse),
            EVENT_STREAM_CONTRACT if service.event_stream().is_available() => Ok(Self::EventStream),
            _ => Err((
                "unsupported_contract",
                "Unsupported desktop automation contract.".to_string(),
            )),
        }
    }

    pub(super) fn dispatch(
        self,
        connection: &mut (impl Read + Write),
        state: &mut ContractState,
        service: &DesktopAutomationService,
        message: &Value,
    ) -> Result<Value, (&'static str, String)> {
        match (self, state) {
            (Self::ComputerUse, ContractState::ComputerUse(state)) => {
                dispatch_request(connection, state, service, message)
            }
            (Self::EventStream, ContractState::EventStream(state)) => state.dispatch(message),
            _ => Err((
                "contract_state_mismatch",
                "Desktop automation connection state is invalid.".to_string(),
            )),
        }
    }

    pub(super) fn state(self, service: &DesktopAutomationService) -> ContractState {
        match self {
            Self::ComputerUse => ContractState::ComputerUse(ServerState::default()),
            Self::EventStream => ContractState::EventStream(EventStreamConnection::new(
                Arc::clone(service.event_stream()),
            )),
        }
    }
}

pub(super) fn hello_result(contract: Contract, service: &DesktopAutomationService) -> Value {
    let mut contracts = Map::new();
    contracts.insert(
        COMPUTER_USE_CONTRACT.to_string(),
        json!(COMPUTER_USE_CONTRACT_VERSION),
    );
    let mut features = COMPUTER_USE_FEATURES.to_vec();
    if service.event_stream().is_available() {
        contracts.insert(
            EVENT_STREAM_CONTRACT.to_string(),
            json!(EVENT_STREAM_CONTRACT_VERSION),
        );
        features.push(EVENT_STREAM_FEATURE);
    }
    let mut result = json!({
        "protocol_version": PROTOCOL_VERSION,
        "contracts": contracts,
        "features": features,
    });
    if contract == Contract::EventStream {
        result["artifact_root"] = json!(service.event_stream().artifact_root());
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    fn service() -> Arc<DesktopAutomationService> {
        let directory = tempfile::tempdir().unwrap().keep();
        DesktopAutomationService::prepare(directory.join("helper.sock").to_str().unwrap()).unwrap()
    }

    #[test]
    fn legacy_v2_defaults_to_the_computer_use_contract() {
        assert_eq!(
            Contract::negotiate(&Map::new(), &service()).unwrap(),
            Contract::ComputerUse,
        );
    }

    #[test]
    fn event_stream_requires_the_native_runtime() {
        let service = service();
        let hello = hello_result(Contract::ComputerUse, &service);
        let params = json!({"contract": "event_stream"})
            .as_object()
            .unwrap()
            .clone();
        if service.event_stream().is_available() {
            assert_eq!(hello["contracts"]["event_stream"], 1);
            assert_eq!(
                Contract::negotiate(&params, &service).unwrap(),
                Contract::EventStream
            );
        } else {
            assert!(hello["contracts"].get("event_stream").is_none());
            assert_eq!(
                Contract::negotiate(&params, &service).unwrap_err().0,
                "unsupported_contract"
            );
        }
    }

    #[test]
    fn hello_advertises_the_versioned_computer_use_contract() {
        let service = service();
        let value = hello_result(Contract::ComputerUse, &service);
        assert_eq!(
            value.get("protocol_version").and_then(Value::as_u64),
            Some(PROTOCOL_VERSION),
        );
        assert_eq!(
            value
                .get("contracts")
                .and_then(|contracts| contracts.get(COMPUTER_USE_CONTRACT))
                .and_then(Value::as_u64),
            Some(COMPUTER_USE_CONTRACT_VERSION),
        );
        let features = value["features"].as_array().unwrap();
        assert!(features.contains(&json!("computer_use.observe")));
        assert!(features.contains(&json!("computer_use.act")));
        assert_eq!(
            features.contains(&json!(EVENT_STREAM_FEATURE)),
            service.event_stream().is_available(),
        );
    }
}
