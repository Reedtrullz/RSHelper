"""Host-supplied contract: old images must understand every acknowledged ledger."""
import argparse
import sys

def main():
    from rshelper import cli, profile, state_identity
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default='default')
    selected = parser.parse_args().profile
    root = profile.resolve_config_path('', selected)
    activation = state_identity.activation_manifest(root / 'identity-activation.json')
    if ((root / 'observed-offers.json').exists() or (root / 'observed-offers.json').is_symlink()
            or (activation or {}).get('observed_offer_origin') is not None):
        from rshelper.observed_offers import read_store
        read_store(selected)
    sys.argv = ['rshelper', '--profile', selected, 'state', 'check', '--json']
    return cli.main()

if __name__ == '__main__':
    sys.exit(main())
