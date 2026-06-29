from goalkeeper.calibration import calibrate_objective
from goalkeeper.ledger import GoalkeeperStore, new_checkpoint_id, utc_now
from goalkeeper.models import Checkpoint


def test_ledger_can_save_load_and_summarize(tmp_path):
    store = GoalkeeperStore(tmp_path)
    contract = calibrate_objective("add search filters", cwd=tmp_path)
    store.save_contract(contract)

    loaded = store.load_contract(contract.id)

    assert loaded.id == contract.id

    checkpoint = Checkpoint(
        id=new_checkpoint_id(),
        contract_id=contract.id,
        timestamp=utc_now(),
        claimed_progress="Implemented filter parser",
        new_evidence=["unit test added"],
    )
    store.append_checkpoint(checkpoint)

    checkpoints = store.read_checkpoints(contract.id)
    summary = store.recent_checkpoint_summary(contract.id)

    assert len(checkpoints) == 1
    assert "Implemented filter parser" in summary
